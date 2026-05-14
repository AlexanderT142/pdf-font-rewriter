import crypto from "crypto";
import fs from "fs/promises";
import path from "path";

import andikaRegular from "../fonts/Andika-Regular.ttf";
import atkinsonHyperlegibleRegular from "../fonts/AtkinsonHyperlegible-Regular.ttf";
import charisSilRegular from "../fonts/CharisSIL-Regular.ttf";
import ebGaramondRegular from "../fonts/EBGaramond-Regular.ttf";
import interRegular from "../fonts/Inter-Regular.ttf";
import latoRegular from "../fonts/Lato-Regular.ttf";
import notoSansRegular from "../fonts/NotoSans-Regular.ttf";
import openDyslexicRegular from "../fonts/OpenDyslexic-Regular.otf";
import openSansRegular from "../fonts/OpenSans-Regular.ttf";
import texGyrePagellaRegular from "../fonts/TeXGyrePagella-Regular.otf";
import xCharterRegular from "../fonts/XCharter-Regular.otf";

import type PdfFontRewriterPlugin from "./main";
import { defaultBuiltinFontsDir } from "./platform";

export const CUSTOM_FONT_ID = "custom";
export const DEFAULT_BUILTIN_FONT_ID = "charis-sil";

export interface BuiltinFont {
  id: string;
  label: string;
  family: "serif" | "sans";
  fileName: string;
  base64Chunks: readonly string[];
}

export const BUILTIN_FONTS: BuiltinFont[] = [
  {
    id: "charis-sil",
    label: "Serif - Charis SIL",
    family: "serif",
    fileName: "CharisSIL-Regular.ttf",
    base64Chunks: charisSilRegular,
  },
  {
    id: "xcharter",
    label: "Serif - XCharter",
    family: "serif",
    fileName: "XCharter-Regular.otf",
    base64Chunks: xCharterRegular,
  },
  {
    id: "tex-gyre-pagella",
    label: "Serif - TeX Gyre Pagella",
    family: "serif",
    fileName: "TeXGyrePagella-Regular.otf",
    base64Chunks: texGyrePagellaRegular,
  },
  {
    id: "eb-garamond",
    label: "Serif - EB Garamond",
    family: "serif",
    fileName: "EBGaramond-Regular.ttf",
    base64Chunks: ebGaramondRegular,
  },
  {
    id: "inter",
    label: "Sans - Inter",
    family: "sans",
    fileName: "Inter-Regular.ttf",
    base64Chunks: interRegular,
  },
  {
    id: "noto-sans",
    label: "Sans - Noto Sans",
    family: "sans",
    fileName: "NotoSans-Regular.ttf",
    base64Chunks: notoSansRegular,
  },
  {
    id: "open-sans",
    label: "Sans - Open Sans",
    family: "sans",
    fileName: "OpenSans-Regular.ttf",
    base64Chunks: openSansRegular,
  },
  {
    id: "lato",
    label: "Sans - Lato",
    family: "sans",
    fileName: "Lato-Regular.ttf",
    base64Chunks: latoRegular,
  },
  {
    id: "atkinson-hyperlegible",
    label: "Sans - Atkinson Hyperlegible",
    family: "sans",
    fileName: "AtkinsonHyperlegible-Regular.ttf",
    base64Chunks: atkinsonHyperlegibleRegular,
  },
  {
    id: "andika",
    label: "Sans - Andika",
    family: "sans",
    fileName: "Andika-Regular.ttf",
    base64Chunks: andikaRegular,
  },
  {
    id: "open-dyslexic",
    label: "Sans - OpenDyslexic",
    family: "sans",
    fileName: "OpenDyslexic-Regular.otf",
    base64Chunks: openDyslexicRegular,
  },
];

export function getBuiltinFont(id: string): BuiltinFont {
  return BUILTIN_FONTS.find((font) => font.id === id) ?? BUILTIN_FONTS[0];
}

export function isBuiltinFontId(id: string): boolean {
  return BUILTIN_FONTS.some((font) => font.id === id);
}

export async function resolveTargetFontPath(plugin: PdfFontRewriterPlugin): Promise<string> {
  if (plugin.settings.targetFontSource === "custom") {
    return plugin.settings.targetFontPath;
  }

  const font = getBuiltinFont(plugin.settings.builtinFontId);
  return ensureBuiltinFontInstalled(font);
}

async function ensureBuiltinFontInstalled(font: BuiltinFont): Promise<string> {
  const fontPath = path.join(defaultBuiltinFontsDir(), font.fileName);
  const buffer = Buffer.from(font.base64Chunks.join(""), "base64");
  const expectedHash = sha256(buffer);

  try {
    const existing = await fs.readFile(fontPath);
    if (sha256(existing) === expectedHash) {
      return fontPath;
    }
  } catch {
    // Missing or unreadable fonts are rewritten from the embedded copy below.
  }

  await fs.mkdir(path.dirname(fontPath), { recursive: true });
  await fs.writeFile(fontPath, buffer);
  return fontPath;
}

function sha256(buffer: Buffer): string {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}
