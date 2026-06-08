import crypto from "crypto";
import fs from "fs/promises";
import os from "os";
import path from "path";
import { pathToFileURL } from "url";

import { BUILTIN_FONTS, installOrUpdateBuiltinFonts } from "../src/builtinFonts";
import { installOrUpdateHelper } from "../src/helperInstaller";
import { HELPER_VERSION } from "../src/helperRelease";
import type { PdfFontRewriterSettings } from "../src/settings";
import { platformTag } from "../src/platform";

interface TestPlugin {
  settings: PdfFontRewriterSettings;
  saveSettings: () => Promise<void>;
}

const releaseDir = process.env.PDF_FONT_REWRITER_RELEASE_DIR;
if (!releaseDir) {
  throw new Error("PDF_FONT_REWRITER_RELEASE_DIR is required.");
}

const installDir = await fs.mkdtemp(path.join(os.tmpdir(), "pdf-font-rewriter-helper-"));
process.env.PDF_FONT_REWRITER_DATA_DIR = path.join(installDir, "data");
const helperPath = path.join(installDir, process.platform === "win32" ? "refont-helper.exe" : "refont-helper");
const settings: PdfFontRewriterSettings = {
  helperPath,
  helperReleaseBaseUrl: pathToFileURL(releaseDir).toString(),
  helperVersion: "",
  helperPlatform: "",
  helperSha256: "",
  targetFontPath: "",
  targetFontSource: "builtin",
  builtinFontId: "charis-sil",
  builtinFontsVersion: "",
  builtinFontSha256: {},
  cjkFallbackPath: "",
  outputMode: "copy",
  outputSuffix: "_refonted",
  openPdfWithLiveView: false,
  pageScope: "visible-window",
  visiblePageRadius: 1,
  pageRange: "",
  openAfterRewrite: true,
  mode: "conservative",
  backups: [],
};

const plugin: TestPlugin = {
  settings,
  saveSettings: async () => undefined,
};

await installOrUpdateHelper(plugin as never);

const installed = await fs.readFile(helperPath);
const digest = crypto.createHash("sha256").update(installed).digest("hex");

if (digest !== plugin.settings.helperSha256) {
  throw new Error(`Installed helper checksum mismatch: ${digest}`);
}

if (plugin.settings.helperPlatform !== platformTag()) {
  throw new Error(`Installed helper platform mismatch: ${plugin.settings.helperPlatform}`);
}

if (plugin.settings.helperVersion !== HELPER_VERSION) {
  throw new Error(`Installed helper version mismatch: ${plugin.settings.helperVersion}`);
}

await installOrUpdateBuiltinFonts(plugin as never);

if (plugin.settings.builtinFontsVersion !== HELPER_VERSION) {
  throw new Error(`Installed font version mismatch: ${plugin.settings.builtinFontsVersion}`);
}

for (const font of BUILTIN_FONTS) {
  const fontPath = path.join(process.env.PDF_FONT_REWRITER_DATA_DIR, "fonts", font.fileName);
  const fontBuffer = await fs.readFile(fontPath);
  const fontDigest = crypto.createHash("sha256").update(fontBuffer).digest("hex");
  if (fontDigest !== plugin.settings.builtinFontSha256[font.fileName]) {
    throw new Error(`Installed font checksum mismatch for ${font.fileName}: ${fontDigest}`);
  }
}

console.log(helperPath);
console.log(path.join(process.env.PDF_FONT_REWRITER_DATA_DIR, "fonts"));
