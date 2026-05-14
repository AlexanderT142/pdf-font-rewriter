import crypto from "crypto";
import fs from "fs/promises";
import os from "os";
import path from "path";
import { pathToFileURL } from "url";

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
const helperPath = path.join(installDir, process.platform === "win32" ? "refont-helper.exe" : "refont-helper");
const settings: PdfFontRewriterSettings = {
  helperPath,
  helperReleaseBaseUrl: pathToFileURL(releaseDir).toString(),
  helperVersion: "",
  helperPlatform: "",
  helperSha256: "",
  targetFontPath: "",
  cjkFallbackPath: "",
  outputMode: "copy",
  outputSuffix: "_refonted",
  pageRange: "",
  openAfterRewrite: true,
  mode: "conservative",
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

console.log(helperPath);
