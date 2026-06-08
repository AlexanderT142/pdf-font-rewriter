import fs from "fs/promises";
import path from "path";

import { Notice } from "obsidian";

import type PdfFontRewriterPlugin from "./main";
import { DEFAULT_HELPER_RELEASE_BASE_URL, FONT_MANIFEST_NAME } from "./helperRelease";
import { defaultBuiltinFontsDir } from "./platform";
import {
  downloadBuffer,
  joinReleaseUrl,
  removeIfExists,
  sha256Buffer,
  sha256File,
} from "./releaseAssets";

export const CUSTOM_FONT_ID = "custom";
export const DEFAULT_BUILTIN_FONT_ID = "charis-sil";

export interface BuiltinFont {
  id: string;
  label: string;
  family: "serif" | "sans";
  fileName: string;
}

interface FontAsset {
  name: string;
  fileName: string;
  sha256: string;
  size_bytes: number;
}

interface FontManifest {
  version: string;
  assets: Record<string, FontAsset>;
}

export const BUILTIN_FONTS: BuiltinFont[] = [
  {
    id: "charis-sil",
    label: "Serif - Charis SIL",
    family: "serif",
    fileName: "CharisSIL-Regular.ttf",
  },
  {
    id: "xcharter",
    label: "Serif - XCharter",
    family: "serif",
    fileName: "XCharter-Regular.otf",
  },
  {
    id: "tex-gyre-pagella",
    label: "Serif - TeX Gyre Pagella",
    family: "serif",
    fileName: "TeXGyrePagella-Regular.otf",
  },
  {
    id: "eb-garamond",
    label: "Serif - EB Garamond",
    family: "serif",
    fileName: "EBGaramond-Regular.ttf",
  },
  {
    id: "inter",
    label: "Sans - Inter",
    family: "sans",
    fileName: "Inter-Regular.ttf",
  },
  {
    id: "noto-sans",
    label: "Sans - Noto Sans",
    family: "sans",
    fileName: "NotoSans-Regular.ttf",
  },
  {
    id: "open-sans",
    label: "Sans - Open Sans",
    family: "sans",
    fileName: "OpenSans-Regular.ttf",
  },
  {
    id: "lato",
    label: "Sans - Lato",
    family: "sans",
    fileName: "Lato-Regular.ttf",
  },
  {
    id: "atkinson-hyperlegible",
    label: "Sans - Atkinson Hyperlegible",
    family: "sans",
    fileName: "AtkinsonHyperlegible-Regular.ttf",
  },
  {
    id: "andika",
    label: "Sans - Andika",
    family: "sans",
    fileName: "Andika-Regular.ttf",
  },
  {
    id: "open-dyslexic",
    label: "Sans - OpenDyslexic",
    family: "sans",
    fileName: "OpenDyslexic-Regular.otf",
  },
];

export function getBuiltinFont(id: string): BuiltinFont {
  return BUILTIN_FONTS.find((font) => font.id === id) ?? BUILTIN_FONTS[0];
}

export function isBuiltinFontId(id: string): boolean {
  return BUILTIN_FONTS.some((font) => font.id === id);
}

export async function installOrUpdateBuiltinFonts(
  plugin: PdfFontRewriterPlugin,
  options: { notify?: boolean } = {},
): Promise<void> {
  const manifest = await fetchFontManifest(fontReleaseBaseUrl(plugin));
  let installedCount = 0;

  for (const font of BUILTIN_FONTS) {
    const installed = await ensureBuiltinFontInstalled(plugin, font, manifest);
    if (installed) {
      installedCount += 1;
    }
  }

  plugin.settings.builtinFontsVersion = manifest.version;
  await plugin.saveSettings();

  if (options.notify) {
    new Notice(`PDF Font Rewriter: ${installedCount} built-in fonts installed.`);
  }
}

export async function resolveTargetFontPath(plugin: PdfFontRewriterPlugin): Promise<string> {
  if (plugin.settings.targetFontSource === "custom") {
    return plugin.settings.targetFontPath;
  }

  const font = getBuiltinFont(plugin.settings.builtinFontId);
  const manifest = await fetchFontManifest(fontReleaseBaseUrl(plugin));
  await ensureBuiltinFontInstalled(plugin, font, manifest);
  return fontPath(font);
}

async function ensureBuiltinFontInstalled(
  plugin: PdfFontRewriterPlugin,
  font: BuiltinFont,
  manifest: FontManifest,
): Promise<boolean> {
  const asset = manifest.assets[font.fileName];
  if (!asset) {
    throw new Error(`No built-in font asset is available for ${font.fileName}.`);
  }

  const targetPath = fontPath(font);
  if (await installedFontMatches(targetPath, manifest.version, asset, plugin.settings)) {
    return false;
  }

  const assetUrl = joinReleaseUrl(fontReleaseBaseUrl(plugin), asset.name);
  const buffer = await downloadBuffer(assetUrl);
  const digest = sha256Buffer(buffer);

  if (digest !== asset.sha256) {
    throw new Error(`Font checksum mismatch for ${font.fileName}. Expected ${asset.sha256}, received ${digest}.`);
  }

  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  const tempPath = `${targetPath}.download`;
  await fs.writeFile(tempPath, buffer);
  await removeIfExists(targetPath);
  await fs.rename(tempPath, targetPath);

  plugin.settings.builtinFontSha256[font.fileName] = asset.sha256;
  plugin.settings.builtinFontsVersion = manifest.version;
  await plugin.saveSettings();
  return true;
}

async function installedFontMatches(
  targetPath: string,
  version: string,
  asset: FontAsset,
  settings: PdfFontRewriterPlugin["settings"],
): Promise<boolean> {
  if (
    settings.builtinFontsVersion !== version ||
    settings.builtinFontSha256[asset.fileName] !== asset.sha256
  ) {
    return false;
  }

  try {
    return (await sha256File(targetPath)) === asset.sha256;
  } catch {
    return false;
  }
}

async function fetchFontManifest(baseUrl: string): Promise<FontManifest> {
  const manifestUrl = joinReleaseUrl(baseUrl, FONT_MANIFEST_NAME);
  const buffer = await downloadBuffer(manifestUrl);
  const manifest = JSON.parse(buffer.toString("utf8")) as FontManifest;
  validateFontManifest(manifest);
  return manifest;
}

function validateFontManifest(manifest: FontManifest): void {
  if (!manifest.version || typeof manifest.version !== "string") {
    throw new Error("Invalid font manifest: missing version.");
  }
  if (!manifest.assets || typeof manifest.assets !== "object") {
    throw new Error("Invalid font manifest: missing assets.");
  }
}

function fontReleaseBaseUrl(plugin: PdfFontRewriterPlugin): string {
  return plugin.settings.helperReleaseBaseUrl || DEFAULT_HELPER_RELEASE_BASE_URL;
}

function fontPath(font: BuiltinFont): string {
  return path.join(defaultBuiltinFontsDir(), font.fileName);
}
