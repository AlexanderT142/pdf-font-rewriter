import crypto from "crypto";
import fs from "fs/promises";
import path from "path";

import atkinsonHyperlegibleRegular from "../fonts/AtkinsonHyperlegible-Regular.ttf";
import firaSansRegular from "../fonts/FiraSans-Regular.ttf";
import libreBaskervilleRegular from "../fonts/LibreBaskerville.ttf";
import libertinusSansRegular from "../fonts/LibertinusSans-Regular.ttf";
import libertinusSerifRegular from "../fonts/LibertinusSerif-Regular.ttf";
import ptSerifRegular from "../fonts/PT_Serif-Web-Regular.ttf";
import sourceSerif4Regular from "../fonts/SourceSerif4.ttf";
import workSansRegular from "../fonts/WorkSans.ttf";

import type PdfFontRewriterPlugin from "./main";
import { defaultBuiltinFontsDir } from "./platform";

export const CUSTOM_FONT_ID = "custom";
export const DEFAULT_BUILTIN_FONT_ID = "libertinus-serif";

export interface BuiltinFont {
  id: string;
  label: string;
  family: "serif" | "sans";
  fileName: string;
  base64: string;
}

export const BUILTIN_FONTS: BuiltinFont[] = [
  {
    id: "libertinus-serif",
    label: "Serif - Libertinus Serif",
    family: "serif",
    fileName: "LibertinusSerif-Regular.ttf",
    base64: libertinusSerifRegular,
  },
  {
    id: "source-serif-4",
    label: "Serif - Source Serif 4",
    family: "serif",
    fileName: "SourceSerif4.ttf",
    base64: sourceSerif4Regular,
  },
  {
    id: "libre-baskerville",
    label: "Serif - Libre Baskerville",
    family: "serif",
    fileName: "LibreBaskerville.ttf",
    base64: libreBaskervilleRegular,
  },
  {
    id: "pt-serif",
    label: "Serif - PT Serif",
    family: "serif",
    fileName: "PT_Serif-Web-Regular.ttf",
    base64: ptSerifRegular,
  },
  {
    id: "libertinus-sans",
    label: "Sans - Libertinus Sans",
    family: "sans",
    fileName: "LibertinusSans-Regular.ttf",
    base64: libertinusSansRegular,
  },
  {
    id: "atkinson-hyperlegible",
    label: "Sans - Atkinson Hyperlegible",
    family: "sans",
    fileName: "AtkinsonHyperlegible-Regular.ttf",
    base64: atkinsonHyperlegibleRegular,
  },
  {
    id: "fira-sans",
    label: "Sans - Fira Sans",
    family: "sans",
    fileName: "FiraSans-Regular.ttf",
    base64: firaSansRegular,
  },
  {
    id: "work-sans",
    label: "Sans - Work Sans",
    family: "sans",
    fileName: "WorkSans.ttf",
    base64: workSansRegular,
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
  const buffer = Buffer.from(font.base64, "base64");
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
