import { Notice, Plugin, TAbstractFile, TFile } from "obsidian";

import { isBuiltinFontId } from "./builtinFonts";
import { DEFAULT_HELPER_RELEASE_BASE_URL } from "./helperRelease";
import { installOrUpdateHelper } from "./helperInstaller";
import { PdfRewriteModal } from "./rewriteModal";
import {
  DEFAULT_SETTINGS,
  PdfFontRewriterSettingTab,
  type PdfFontRewriterSettings,
} from "./settings";

export default class PdfFontRewriterPlugin extends Plugin {
  settings: PdfFontRewriterSettings = DEFAULT_SETTINGS;

  async onload(): Promise<void> {
    await this.loadSettings();

    this.addRibbonIcon("type", "Rewrite PDF font", () => {
      this.openRewriteModalForActiveFile();
    }).addClass("pdf-font-rewriter-ribbon-icon");

    this.addCommand({
      id: "rewrite-active-pdf-font",
      name: "Rewrite active PDF font",
      checkCallback: (checking) => {
        const file = this.app.workspace.getActiveFile();
        const canRun = file instanceof TFile && file.extension.toLowerCase() === "pdf";
        if (checking) {
          return canRun;
        }
        if (!canRun || !file) {
          new Notice("PDF Font Rewriter: open a PDF file first.");
          return false;
        }
        this.openRewriteModal(file);
        return true;
      },
    });

    this.addCommand({
      id: "install-or-update-helper",
      name: "Install or update helper",
      callback: () => {
        installOrUpdateHelper(this)
          .then(() => new Notice("PDF Font Rewriter: helper is ready."))
          .catch((error: unknown) => {
            console.error(error);
            new Notice("PDF Font Rewriter: helper install failed.");
          });
      },
    });

    this.registerEvent(
      this.app.workspace.on("file-menu", (menu, file) => {
        if (!isPdfFile(file)) {
          return;
        }

        menu.addItem((item) => {
          item
            .setTitle("Rewrite PDF font")
            .setIcon("type")
            .onClick(() => this.openRewriteModal(file));
        });
      }),
    );

    this.addSettingTab(new PdfFontRewriterSettingTab(this.app, this));
  }

  async loadSettings(): Promise<void> {
    const loaded = (await this.loadData()) as unknown;
    const savedSettings = isSettingsRecord(loaded) ? loaded : {};
    this.settings = { ...DEFAULT_SETTINGS, ...savedSettings };
    let migrated = false;

    if (!Object.prototype.hasOwnProperty.call(savedSettings, "targetFontSource")) {
      this.settings.targetFontSource = this.settings.targetFontPath ? "custom" : "builtin";
      migrated = true;
    }
    if (!this.settings.builtinFontId || !isBuiltinFontId(this.settings.builtinFontId)) {
      this.settings.builtinFontId = DEFAULT_SETTINGS.builtinFontId;
      migrated = true;
    }
    if (this.settings.outputMode !== "copy" && this.settings.outputMode !== "replace") {
      this.settings.outputMode = DEFAULT_SETTINGS.outputMode;
      migrated = true;
    }
    if (shouldMigrateHelperReleaseUrl(savedSettings.helperReleaseBaseUrl)) {
      this.settings.helperReleaseBaseUrl = DEFAULT_HELPER_RELEASE_BASE_URL;
      migrated = true;
    }

    if (migrated) {
      await this.saveSettings();
    }
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  openRewriteModal(file: TFile): void {
    new PdfRewriteModal(this, file).open();
  }

  openRewriteModalForActiveFile(): void {
    const file = this.app.workspace.getActiveFile();
    if (!isPdfFile(file)) {
      new Notice("PDF Font Rewriter: open a PDF file first.");
      return;
    }

    this.openRewriteModal(file);
  }
}

function isSettingsRecord(value: unknown): value is Partial<PdfFontRewriterSettings> {
  return typeof value === "object" && value !== null;
}

function isPdfFile(file: TAbstractFile | null): file is TFile {
  return file instanceof TFile && file.extension.toLowerCase() === "pdf";
}

function shouldMigrateHelperReleaseUrl(value: unknown): boolean {
  if (typeof value !== "string" || !value.trim()) {
    return true;
  }

  return /^https:\/\/github\.com\/AlexanderT142\/pdf-font-rewriter\/releases\/download\/v?\d+\.\d+\.\d+$/.test(
    value.trim(),
  );
}
