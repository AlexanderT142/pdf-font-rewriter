import fs from "fs/promises";
import path from "path";

import { Notice } from "obsidian";

import {
  BUILTIN_FONTS,
  CUSTOM_FONT_ID,
  isBuiltinFontId,
} from "./builtinFonts";
import type PdfFontRewriterPlugin from "./main";
import { defaultCustomFontsDir } from "./platform";
import type { PdfFontRewriterSettings } from "./settings";

export const IMPORT_CUSTOM_FONT_ID = "__import-custom-font__";
export const ORIGINAL_PDF_FONT_ID = "__original-pdf__";

interface FontOption {
  value: string;
  label: string;
}

interface FontOptionOptions {
  includeCustomPath?: boolean;
  includeOriginal?: boolean;
  includeImport?: boolean;
}

export function targetFontSelectValue(settings: PdfFontRewriterSettings): string {
  return settings.targetFontSource === "custom" ? CUSTOM_FONT_ID : settings.builtinFontId;
}

export function targetFontOptions(
  settings: PdfFontRewriterSettings,
  options: FontOptionOptions = {},
): FontOption[] {
  const fontOptions = BUILTIN_FONTS.map((font) => ({
    value: font.id,
    label: font.label,
  }));

  if (options.includeOriginal) {
    fontOptions.unshift({
      value: ORIGINAL_PDF_FONT_ID,
      label: "Original PDF",
    });
  }

  if (options.includeCustomPath) {
    fontOptions.push({
      value: CUSTOM_FONT_ID,
      label: customFontLabel(settings.targetFontPath),
    });
  }

  if (options.includeImport) {
    fontOptions.push({
      value: IMPORT_CUSTOM_FONT_ID,
      label: "Import .ttf/.otf...",
    });
  }

  return fontOptions;
}

export async function applyTargetFontSelection(
  plugin: PdfFontRewriterPlugin,
  value: string,
): Promise<boolean> {
  if (value === IMPORT_CUSTOM_FONT_ID) {
    return importCustomFont(plugin);
  }

  const previousSource = plugin.settings.targetFontSource;
  const previousBuiltin = plugin.settings.builtinFontId;
  const previousPath = plugin.settings.targetFontPath;

  if (value === CUSTOM_FONT_ID) {
    plugin.settings.targetFontSource = "custom";
  } else if (isBuiltinFontId(value)) {
    plugin.settings.targetFontSource = "builtin";
    plugin.settings.builtinFontId = value;
  } else {
    return false;
  }

  await plugin.saveSettings();
  return (
    previousSource !== plugin.settings.targetFontSource ||
    previousBuiltin !== plugin.settings.builtinFontId ||
    previousPath !== plugin.settings.targetFontPath
  );
}

export async function importCustomFont(plugin: PdfFontRewriterPlugin): Promise<boolean> {
  const fontFile = await chooseFontFile();
  if (!fontFile) {
    return false;
  }

  const targetPath = await copyFontToAppData(fontFile);
  plugin.settings.targetFontSource = "custom";
  plugin.settings.targetFontPath = targetPath;
  await plugin.saveSettings();
  new Notice(`PDF Font Rewriter: imported ${fontFile.name}.`);
  return true;
}

function customFontLabel(fontPath: string): string {
  if (!fontPath.trim()) {
    return "Custom font path";
  }

  return `Custom - ${path.basename(fontPath)}`;
}

function chooseFontFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = activeDocument.createElement("input");
    let settled = false;

    input.type = "file";
    input.accept = ".ttf,.otf,font/ttf,font/otf,application/font-sfnt";
    input.addClass("pdf-font-rewriter-hidden");

    const finish = (file: File | null): void => {
      if (settled) {
        return;
      }
      settled = true;
      input.remove();
      resolve(file);
    };

    input.addEventListener(
      "change",
      () => {
        finish(input.files?.[0] ?? null);
      },
      { once: true },
    );
    activeWindow.addEventListener(
      "focus",
      () => {
        activeWindow.setTimeout(() => {
          if (!input.files || input.files.length === 0) {
            finish(null);
          }
        }, 250);
      },
      { once: true },
    );

    activeDocument.body.appendChild(input);
    input.click();
  });
}

async function copyFontToAppData(fontFile: File): Promise<string> {
  const fileName = safeFontFileName(fontFile.name);
  const targetDir = defaultCustomFontsDir();
  const targetPath = path.join(targetDir, `${Date.now()}-${fileName}`);
  const fontBuffer = Buffer.from(await fontFile.arrayBuffer());

  if (fontBuffer.byteLength === 0) {
    throw new Error("Selected font file is empty.");
  }

  await fs.mkdir(targetDir, { recursive: true });
  await fs.writeFile(targetPath, fontBuffer);
  return targetPath;
}

function safeFontFileName(fileName: string): string {
  const extension = path.extname(fileName).toLowerCase();
  if (extension !== ".ttf" && extension !== ".otf") {
    throw new Error("Choose a .ttf or .otf font file.");
  }

  const baseName = path.basename(fileName, extension).replace(/[^A-Za-z0-9._-]+/g, "-");
  return `${baseName || "custom-font"}${extension}`;
}
