import crypto from "crypto";
import fs from "fs/promises";
import http from "http";
import https from "https";
import path from "path";
import { fileURLToPath } from "url";

import { Notice } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import {
  HELPER_MANIFEST_NAME,
  type HelperAsset,
  type HelperManifest,
} from "./helperRelease";
import { defaultHelperPath, platformTag } from "./platform";

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
  const assetUrl = joinUrl(plugin.settings.helperReleaseBaseUrl, asset.name);
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
  const manifestUrl = joinUrl(baseUrl, HELPER_MANIFEST_NAME);
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

function joinUrl(baseUrl: string, fileName: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/${encodeURIComponent(fileName)}`;
}

async function downloadBuffer(url: string, redirects = 0): Promise<Buffer> {
  if (url.startsWith("file:")) {
    return fs.readFile(fileURLToPath(url));
  }

  if (redirects > 5) {
    throw new Error(`Too many redirects while downloading ${url}`);
  }

  return new Promise((resolve, reject) => {
    const client = url.startsWith("https:") ? https : http;
    const request = client.get(
      url,
      {
        headers: {
          "User-Agent": "pdf-font-rewriter-obsidian",
        },
      },
      (response) => {
        const statusCode = response.statusCode ?? 0;
        const location = response.headers.location;

        if (statusCode >= 300 && statusCode < 400 && location) {
          response.resume();
          const redirectUrl = new URL(location, url).toString();
          downloadBuffer(redirectUrl, redirects + 1).then(resolve, reject);
          return;
        }

        if (statusCode !== 200) {
          response.resume();
          reject(new Error(`Download failed with HTTP ${statusCode}: ${url}`));
          return;
        }

        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => resolve(Buffer.concat(chunks)));
      },
    );

    request.on("error", reject);
  });
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

async function sha256File(filePath: string): Promise<string> {
  const buffer = await fs.readFile(filePath);
  return sha256Buffer(buffer);
}

function sha256Buffer(buffer: Buffer): string {
  return crypto.createHash("sha256").update(buffer).digest("hex");
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
