import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import { createHash } from "crypto";
import fs from "fs/promises";
import path from "path";

import { FileSystemAdapter, TFile } from "obsidian";

import { resolveTargetFontPath } from "./builtinFonts";
import { ensureHelperInstalled } from "./helperInstaller";
import type { LiveRefontJsonRpcResponse, LiveRefontPagePlan } from "./liveRefontProtocol";
import type PdfFontRewriterPlugin from "./main";

const REQUEST_TIMEOUT_MS = 1000 * 45;
const loadedFontFamilies = new Set<string>();

interface PendingRequest {
  resolve: (plan: LiveRefontPagePlan) => void;
  reject: (error: Error) => void;
  timeout: number;
}

export class LiveRefontClient {
  private plugin: PdfFontRewriterPlugin;
  private file: TFile;
  private child: ChildProcessWithoutNullStreams | null = null;
  private stdoutBuffer = "";
  private nextRequestId = 1;
  private pending = new Map<string, PendingRequest>();
  private planCache = new Map<number, Promise<LiveRefontPagePlan>>();
  private setupPromise: Promise<void> | null = null;
  private helperPath = "";
  private pdfPath = "";
  private pdfFingerprint = "";
  private fontPath = "";
  private fontHash = "";
  private fontFamily = "";

  constructor(plugin: PdfFontRewriterPlugin, file: TFile) {
    this.plugin = plugin;
    this.file = file;
  }

  async planPage(pageIndex: number): Promise<LiveRefontPagePlan> {
    const cached = this.planCache.get(pageIndex);
    if (cached) {
      return cached;
    }

    const promise = this.requestPlanPage(pageIndex).catch((error: unknown) => {
      this.planCache.delete(pageIndex);
      throw error;
    });
    this.planCache.set(pageIndex, promise);
    return promise;
  }

  async targetFontFamily(): Promise<string> {
    await this.ensureSetup();
    return this.fontFamily;
  }

  cancel(pageIndex: number): void {
    if (!this.child) {
      return;
    }
    const id = `cancel-${pageIndex}-${this.nextRequestId++}`;
    this.child.stdin.write(JSON.stringify({ id, method: "cancel", params: { pageIndex } }) + "\n");
  }

  dispose(): void {
    for (const [id, pending] of this.pending) {
      window.clearTimeout(pending.timeout);
      pending.reject(new Error("Live refont client disposed."));
      this.pending.delete(id);
    }
    this.child?.kill();
    this.child = null;
  }

  private async requestPlanPage(pageIndex: number): Promise<LiveRefontPagePlan> {
    await this.ensureSetup();
    const child = this.ensureChild();
    const id = `plan-${this.nextRequestId++}`;

    const request = {
      id,
      method: "planPage",
      params: {
        pdfPath: this.pdfPath,
        pdfFingerprint: this.pdfFingerprint,
        pageIndex,
        fontPath: this.fontPath,
        fontHash: this.fontHash,
        cjkFallbackPath: this.plugin.settings.cjkFallbackPath || undefined,
        mode: this.plugin.settings.mode,
      },
    };

    return new Promise<LiveRefontPagePlan>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Live refont planner timed out for page ${pageIndex + 1}.`));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timeout });
      child.stdin.write(JSON.stringify(request) + "\n");
    });
  }

  private async ensureSetup(): Promise<void> {
    this.setupPromise ??= this.setup();
    return this.setupPromise;
  }

  private async setup(): Promise<void> {
    const adapter = this.plugin.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) {
      throw new Error("Live Refont View requires a desktop file-system vault.");
    }

    this.helperPath = await ensureHelperInstalled(this.plugin);
    this.pdfPath = adapter.getFullPath(this.file.path);
    this.pdfFingerprint = `vault:${this.file.path}:${this.file.stat.mtime}:${this.file.stat.size}`;
    this.fontPath = await resolveTargetFontPath(this.plugin);
    const fontBuffer = await fs.readFile(this.fontPath);
    this.fontHash = sha256(fontBuffer);
    this.fontFamily = `PdfFontRewriterLive-${this.fontHash.slice(0, 12)}`;
    await loadFontFace(this.fontFamily, fontBuffer);
  }

  private ensureChild(): ChildProcessWithoutNullStreams {
    if (this.child && !this.child.killed) {
      return this.child;
    }

    const child = spawn(this.helperPath, ["live-server"], {
      cwd: path.dirname(this.pdfPath),
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;
    this.stdoutBuffer = "";

    child.stdout.on("data", (chunk: Buffer) => {
      this.stdoutBuffer += chunk.toString("utf8");
      const lines = this.stdoutBuffer.split(/\r?\n/);
      this.stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) {
        this.handleResponseLine(line);
      }
    });

    child.stderr.on("data", (chunk: Buffer) => {
      console.warn("PDF Font Rewriter live planner stderr:", chunk.toString("utf8"));
    });

    child.on("error", (error) => {
      this.rejectAll(error);
    });
    child.on("close", (code, signal) => {
      this.child = null;
      const suffix = signal ? `signal ${signal}` : `exit code ${code}`;
      this.rejectAll(new Error(`Live refont planner exited with ${suffix}.`));
    });

    return child;
  }

  private handleResponseLine(line: string): void {
    if (!line.trim()) {
      return;
    }

    let response: LiveRefontJsonRpcResponse;
    try {
      response = JSON.parse(line) as LiveRefontJsonRpcResponse;
    } catch (error) {
      console.warn("PDF Font Rewriter live planner returned invalid JSON.", error, line);
      return;
    }

    const pending = this.pending.get(response.id);
    if (!pending) {
      return;
    }

    this.pending.delete(response.id);
    window.clearTimeout(pending.timeout);
    if (response.error) {
      pending.reject(new Error(response.error.message));
      return;
    }
    if (!response.result || "cancelled" in response.result) {
      pending.reject(new Error("Live refont planner did not return a page plan."));
      return;
    }
    pending.resolve(response.result);
  }

  private rejectAll(error: Error): void {
    for (const [id, pending] of this.pending) {
      window.clearTimeout(pending.timeout);
      pending.reject(error);
      this.pending.delete(id);
    }
  }
}

async function loadFontFace(family: string, buffer: Buffer): Promise<void> {
  if (!("FontFace" in window) || !document.fonts) {
    return;
  }

  if (loadedFontFamilies.has(family)) {
    return;
  }

  const data = new Uint8Array(buffer.byteLength);
  data.set(buffer);
  const face = new FontFace(family, data);
  await face.load();
  (document.fonts as FontFaceSet & { add: (font: FontFace) => void }).add(face);
  loadedFontFamilies.add(family);
}

function sha256(buffer: Buffer): string {
  return createHash("sha256").update(buffer).digest("hex");
}
