import { spawn } from "child_process";
import fs from "fs/promises";
import path from "path";

import { FileSystemAdapter, Notice, TFile, normalizePath } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import { resolveTargetFontPath } from "./builtinFonts";
import { ensureHelperInstalled } from "./helperInstaller";

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
  const outputVaultPath = await nextOutputPath(plugin, file);
  const reportVaultPath = outputVaultPath.replace(/\.pdf$/i, "_audit.json");
  const outputPath = adapter.getFullPath(outputVaultPath);
  const reportPath = adapter.getFullPath(reportVaultPath);
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
    outputPath,
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

    new Notice(`PDF Font Rewriter: created ${outputVaultPath}`);
    if (settings.openAfterRewrite) {
      await openVaultFile(plugin, outputVaultPath, file.path);
    }
  } catch (error) {
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
