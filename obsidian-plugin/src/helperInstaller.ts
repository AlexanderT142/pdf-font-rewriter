import fs from "fs/promises";
import path from "path";

import { Notice } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import {
  HELPER_MANIFEST_NAME,
  type HelperAsset,
  type HelperManifest,
} from "./helperRelease";
import { defaultHelperPath, platformTag } from "./platform";
import {
  assertReadableFile,
  downloadBuffer,
  joinReleaseUrl,
  removeIfExists,
  sha256Buffer,
  sha256File,
} from "./releaseAssets";

export async function ensureHelperInstalled(plugin: PdfFontRewriterPlugin): Promise<string> {
  const settings = plugin.settings;
  const helperPath = settings.helperPath || defaultHelperPath();

  if (settings.helperReleaseBaseUrl) {
    const tag = platformTag();
    const manifest = await fetchHelperManifest(settings.helperReleaseBaseUrl);
    const asset = manifest.assets[tag];

    if (!asset) {
      throw new Error(`No helper binary is available for ${tag}.`);
    }

    const installed = await installedHelperMatches(helperPath, manifest.version, tag, asset, settings);
    if (installed) {
      return helperPath;
    }

    new Notice("PDF Font Rewriter: installing helper.");
    await installHelper(plugin, manifest, asset, helperPath);
    return helperPath;
  }

  await assertReadableFile(helperPath, "helper binary");
  return helperPath;
}

export async function installOrUpdateHelper(plugin: PdfFontRewriterPlugin): Promise<string> {
  if (!plugin.settings.helperReleaseBaseUrl) {
    throw new Error("Missing helper release URL.");
  }

  const helperPath = plugin.settings.helperPath || defaultHelperPath();
  const tag = platformTag();
  const manifest = await fetchHelperManifest(plugin.settings.helperReleaseBaseUrl);
  const asset = manifest.assets[tag];

  if (!asset) {
    throw new Error(`No helper binary is available for ${tag}.`);
  }

  await installHelper(plugin, manifest, asset, helperPath);
  return helperPath;
}

async function installHelper(
  plugin: PdfFontRewriterPlugin,
  manifest: HelperManifest,
  asset: HelperAsset,
  helperPath: string,
): Promise<void> {
  const assetUrl = joinReleaseUrl(plugin.settings.helperReleaseBaseUrl, asset.name);
  const buffer = await downloadBuffer(assetUrl);
  const digest = sha256Buffer(buffer);

  if (digest !== asset.sha256) {
    throw new Error(`Helper checksum mismatch. Expected ${asset.sha256}, received ${digest}.`);
  }

  await fs.mkdir(path.dirname(helperPath), { recursive: true });
  const tempPath = `${helperPath}.download`;
  await fs.writeFile(tempPath, buffer);

  if (process.platform !== "win32") {
    await fs.chmod(tempPath, 0o755);
  }

  await removeIfExists(helperPath);
  await fs.rename(tempPath, helperPath);

  plugin.settings.helperPath = helperPath;
  plugin.settings.helperVersion = manifest.version;
  plugin.settings.helperPlatform = asset.platform;
  plugin.settings.helperSha256 = asset.sha256;
  await plugin.saveSettings();

  new Notice(`PDF Font Rewriter: helper ${manifest.version} installed.`);
}

async function installedHelperMatches(
  helperPath: string,
  version: string,
  tag: string,
  asset: HelperAsset,
  settings: PdfFontRewriterPlugin["settings"],
): Promise<boolean> {
  if (
    settings.helperVersion !== version ||
    settings.helperPlatform !== tag ||
    settings.helperSha256 !== asset.sha256
  ) {
    return false;
  }

  try {
    const digest = await sha256File(helperPath);
    return digest === asset.sha256;
  } catch {
    return false;
  }
}

async function fetchHelperManifest(baseUrl: string): Promise<HelperManifest> {
  const manifestUrl = joinReleaseUrl(baseUrl, HELPER_MANIFEST_NAME);
  const buffer = await downloadBuffer(manifestUrl);
  const manifest = JSON.parse(buffer.toString("utf8")) as HelperManifest;
  validateManifest(manifest);
  return manifest;
}

function validateManifest(manifest: HelperManifest): void {
  if (!manifest.version || typeof manifest.version !== "string") {
    throw new Error("Invalid helper manifest: missing version.");
  }
  if (!manifest.assets || typeof manifest.assets !== "object") {
    throw new Error("Invalid helper manifest: missing assets.");
  }
}
