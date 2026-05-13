import { execFile } from "child_process";
import fs from "fs/promises";
import path from "path";
import { promisify } from "util";

import { FileSystemAdapter, Notice, TFile, normalizePath } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import { ensureHelperInstalled } from "./helperInstaller";

const execFileAsync = promisify(execFile);

export async function rewriteActivePdf(plugin: PdfFontRewriterPlugin, file: TFile): Promise<void> {
  if (file.extension.toLowerCase() !== "pdf") {
    new Notice("PDF Font Rewriter: active file is not a PDF.");
    return;
  }

  const settings = plugin.settings;
  const helperPath = await ensureHelperInstalled(plugin);
  await assertReadableFile(settings.targetFontPath, "target font");
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

  const args = [
    inputPath,
    "--font",
    settings.targetFontPath,
    "--output",
    outputPath,
    "--report",
    reportPath,
    "--mode",
    settings.mode,
  ];

  if (settings.cjkFallbackPath) {
    args.push("--cjk-fallback", settings.cjkFallbackPath);
  }

  new Notice("PDF Font Rewriter: conversion started.");

  try {
    const { stderr } = await execFileAsync(helperPath, args, {
      cwd: path.dirname(inputPath),
      maxBuffer: 1024 * 1024 * 8,
      timeout: 1000 * 60 * 10,
    });

    if (stderr.trim()) {
      console.warn("PDF Font Rewriter helper stderr:", stderr);
    }

    new Notice(`PDF Font Rewriter: created ${outputVaultPath}`);
  } catch (error) {
    console.error(error);
    new Notice("PDF Font Rewriter failed. Check the developer console for details.");
    throw error;
  }
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
