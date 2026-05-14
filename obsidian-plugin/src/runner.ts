import { spawn } from "child_process";
import fs from "fs/promises";
import path from "path";

import { FileSystemAdapter, Notice, TFile, normalizePath } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import { resolveTargetFontPath } from "./builtinFonts";
import { ensureHelperInstalled } from "./helperInstaller";
import { defaultReportsDir } from "./platform";

const HELPER_TIMEOUT_MS = 1000 * 60 * 10;

export async function rewriteActivePdf(plugin: PdfFontRewriterPlugin, file: TFile): Promise<void> {
  if (file.extension.toLowerCase() !== "pdf") {
    new Notice("PDF Font Rewriter: active file is not a PDF.");
    return;
  }

  const settings = plugin.settings;
  const helperPath = await ensureHelperInstalled(plugin);
  const targetFontPath = await resolveTargetFontPath(plugin);
  await assertReadableFile(targetFontPath, "target font");
  if (settings.cjkFallbackPath) {
    await assertReadableFile(settings.cjkFallbackPath, "CJK fallback font");
  }

  const adapter = plugin.app.vault.adapter;
  if (!(adapter instanceof FileSystemAdapter)) {
    throw new Error("PDF Font Rewriter requires a desktop file-system vault.");
  }

  const inputPath = adapter.getFullPath(file.path);
  await fs.mkdir(defaultReportsDir(), { recursive: true });
  const outputTarget = await rewriteOutputTarget(plugin, file, adapter);
  const reportPath = nextReportPath(file);
  let pageRange = "";
  try {
    pageRange = normalizePageRange(settings.pageRange);
  } catch (error) {
    new Notice('PDF Font Rewriter: pages must look like "1-3,8".');
    throw error;
  }

  const args = [
    inputPath,
    "--font",
    targetFontPath,
    "--output",
    outputTarget.path,
    "--report",
    reportPath,
    "--mode",
    settings.mode,
    "--verbose",
  ];

  if (settings.cjkFallbackPath) {
    args.push("--cjk-fallback", settings.cjkFallbackPath);
  }

  if (pageRange) {
    args.push("--pages", pageRange);
  }

  new Notice(
    pageRange
      ? `PDF Font Rewriter: converting pages ${pageRange}.`
      : "PDF Font Rewriter: converting the whole PDF.",
  );

  try {
    await runHelper(helperPath, args, {
      cwd: path.dirname(inputPath),
      onPage: (page) => {
        if (page === 1 || page % 10 === 0) {
          new Notice(`PDF Font Rewriter: reached page ${page}.`);
        }
      },
    });

    const reportSummary = await readRewriteReportSummary(reportPath);
    if (reportSummary?.changedPages === 0) {
      await removeIfExists(outputTarget.path);
      await removeIfExists(reportPath);
      new Notice(reportSummary.message);
      return;
    }

    if (outputTarget.mode === "replace") {
      if (!reportSummary) {
        await removeIfExists(outputTarget.path);
        new Notice(
          "PDF Font Rewriter: original PDF was left unchanged because the conversion report could not be verified.",
        );
        return;
      }

      await replaceVaultFile(plugin, file, outputTarget.path);
      await removeIfExists(outputTarget.path);
      new Notice(
        `PDF Font Rewriter: updated ${file.path} (${pluralize(reportSummary.changedPages, "page")} changed).`,
      );
      if (settings.openAfterRewrite) {
        await reopenVaultFile(plugin, file);
      }
      return;
    }

    const resultNotice = reportSummary
      ? `PDF Font Rewriter: created ${outputTarget.vaultPath} (${pluralize(reportSummary.changedPages, "page")} changed).`
      : `PDF Font Rewriter: created ${outputTarget.vaultPath}`;
    new Notice(resultNotice);
    if (settings.openAfterRewrite) {
      await openVaultFile(plugin, outputTarget.vaultPath, file.path);
    }
  } catch (error) {
    if (outputTarget.mode === "replace") {
      await removeIfExists(outputTarget.path).catch((cleanupError: unknown) => {
        console.warn("PDF Font Rewriter: could not remove temporary output.", cleanupError);
      });
    }
    console.error(error);
    new Notice("PDF Font Rewriter failed. Check the developer console for details.");
    throw error;
  }
}

async function runHelper(
  helperPath: string,
  args: string[],
  options: { cwd: string; onPage: (page: number) => void },
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(helperPath, args, {
      cwd: options.cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdoutBuffer = "";
    let stderr = "";
    let settled = false;

    const finish = (error?: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timeout);
      if (stderr.trim()) {
        console.warn("PDF Font Rewriter helper stderr:", stderr);
      }
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    };

    const timeout = window.setTimeout(() => {
      child.kill();
      finish(new Error("PDF Font Rewriter helper timed out after 10 minutes."));
    }, HELPER_TIMEOUT_MS);

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutBuffer += chunk.toString("utf8");
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) {
        handleHelperOutputLine(line, options.onPage);
      }
    });

    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });

    child.on("error", (error) => finish(error));
    child.on("close", (code, signal) => {
      if (stdoutBuffer) {
        handleHelperOutputLine(stdoutBuffer, options.onPage);
      }
      if (code === 0) {
        finish();
        return;
      }
      const suffix = signal ? `signal ${signal}` : `exit code ${code}`;
      finish(new Error(`PDF Font Rewriter helper failed with ${suffix}.`));
    });
  });
}

function handleHelperOutputLine(line: string, onPage: (page: number) => void): void {
  const match = /^page\s+(\d+):/.exec(line.trim());
  if (!match) {
    return;
  }
  onPage(Number(match[1]));
}

async function openVaultFile(
  plugin: PdfFontRewriterPlugin,
  vaultPath: string,
  sourcePath: string,
): Promise<void> {
  const outputFile = await waitForVaultFile(plugin, vaultPath);
  if (outputFile) {
    await plugin.app.workspace.getLeaf(false).openFile(outputFile);
    return;
  }

  if (await plugin.app.vault.adapter.exists(vaultPath)) {
    await plugin.app.workspace.openLinkText(vaultPath, sourcePath, false);
    return;
  }

  new Notice(`PDF Font Rewriter: open ${vaultPath} from the file explorer.`);
}

async function reopenVaultFile(plugin: PdfFontRewriterPlugin, file: TFile): Promise<void> {
  const leaf = plugin.app.workspace.getMostRecentLeaf() ?? plugin.app.workspace.getLeaf(false);
  await leaf.openFile(file);
}

async function replaceVaultFile(
  plugin: PdfFontRewriterPlugin,
  file: TFile,
  replacementPath: string,
): Promise<void> {
  const replacement = await fs.readFile(replacementPath);
  const data = replacement.buffer.slice(
    replacement.byteOffset,
    replacement.byteOffset + replacement.byteLength,
  ) as ArrayBuffer;
  await plugin.app.vault.modifyBinary(file, data);
}

interface RewriteReport {
  pages_fully_converted?: unknown;
  pages_partially_converted?: unknown;
  pages_skipped?: unknown;
  skipped_reasons?: unknown;
}

interface RewriteReportSummary {
  changedPages: number;
  message: string;
}

async function readRewriteReportSummary(reportPath: string): Promise<RewriteReportSummary | null> {
  try {
    const raw = await fs.readFile(reportPath, "utf8");
    const report = JSON.parse(raw) as RewriteReport;
    const fully = numberField(report.pages_fully_converted);
    const partial = numberField(report.pages_partially_converted);
    const skipped = numberField(report.pages_skipped);
    const changedPages = fully + partial;

    if (changedPages > 0) {
      return {
        changedPages,
        message: "",
      };
    }

    if (skipped > 0) {
      const reason = topSkippedReason(report.skipped_reasons);
      const suffix = reason
        ? ` Most common reason: ${reason}.`
        : " The selected page could not be rewritten safely.";
      return {
        changedPages,
        message: `PDF Font Rewriter: no text changed, so no output PDF was kept.${suffix}`,
      };
    }

    return {
      changedPages,
      message:
        "PDF Font Rewriter: no selected pages were inside the PDF. Use PDF sheet numbers, not printed book page labels.",
    };
  } catch (error) {
    console.warn("PDF Font Rewriter: could not read conversion report.", error);
    return null;
  }
}

function numberField(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function topSkippedReason(value: unknown): string | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const entries = Object.entries(value as Record<string, unknown>)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .sort((a, b) => b[1] - a[1]);

  return entries[0]?.[0] ?? null;
}

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

async function waitForVaultFile(
  plugin: PdfFontRewriterPlugin,
  vaultPath: string,
): Promise<TFile | null> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const file = plugin.app.vault.getAbstractFileByPath(vaultPath);
    if (file instanceof TFile) {
      return file;
    }
    await sleep(250);
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

type RewriteOutputTarget =
  | { mode: "copy"; path: string; vaultPath: string }
  | { mode: "replace"; path: string };

async function rewriteOutputTarget(
  plugin: PdfFontRewriterPlugin,
  file: TFile,
  adapter: FileSystemAdapter,
): Promise<RewriteOutputTarget> {
  if (plugin.settings.outputMode === "replace") {
    return {
      mode: "replace",
      path: tempOutputPath(file),
    };
  }

  const vaultPath = await nextOutputPath(plugin, file);
  return {
    mode: "copy",
    path: adapter.getFullPath(vaultPath),
    vaultPath,
  };
}

async function nextOutputPath(plugin: PdfFontRewriterPlugin, file: TFile): Promise<string> {
  const folder = file.parent?.path ?? "";
  const suffix = plugin.settings.outputSuffix || "_refonted";
  const base = file.basename;

  for (let index = 0; index < 1000; index += 1) {
    const candidateName = index === 0 ? `${base}${suffix}.pdf` : `${base}${suffix}_${index + 1}.pdf`;
    const candidatePath = normalizePath(folder ? `${folder}/${candidateName}` : candidateName);
    const exists = await plugin.app.vault.adapter.exists(candidatePath);
    if (!exists) {
      return candidatePath;
    }
  }

  throw new Error(`Could not find a free output name for ${file.path}`);
}

function nextReportPath(file: TFile): string {
  const safeName = safeFileBase(file);
  return path.join(defaultReportsDir(), `${Date.now()}-${safeName}-audit.json`);
}

function tempOutputPath(file: TFile): string {
  return path.join(defaultReportsDir(), `${Date.now()}-${safeFileBase(file)}-output.pdf`);
}

function safeFileBase(file: TFile): string {
  return file.basename.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80) || "pdf";
}

function normalizePageRange(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  const parts = trimmed.split(",");
  const normalizedParts = parts.map((part) => {
    const token = part.trim();
    if (!token) {
      throw new Error('Pages to rewrite must look like "1-3,8".');
    }

    const range = token.split("-").map((item) => item.trim());
    if (range.length > 2 || !range.every((item) => /^\d+$/.test(item))) {
      throw new Error('Pages to rewrite must look like "1-3,8".');
    }

    const start = Number(range[0]);
    const end = range.length === 2 ? Number(range[1]) : start;
    if (start < 1 || end < start) {
      throw new Error('Pages to rewrite must look like "1-3,8".');
    }

    return range.length === 2 ? `${start}-${end}` : `${start}`;
  });

  return normalizedParts.join(",");
}

async function assertReadableFile(filePath: string, label: string): Promise<void> {
  if (!filePath) {
    throw new Error(`Missing ${label} path.`);
  }

  try {
    await fs.access(filePath);
  } catch {
    throw new Error(`Cannot read ${label}: ${filePath}`);
  }
}

async function removeIfExists(filePath: string): Promise<void> {
  try {
    await fs.unlink(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
}
