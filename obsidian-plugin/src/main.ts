import { Notice, Plugin, TFile } from "obsidian";

import { installOrUpdateHelper } from "./helperInstaller";
import { rewriteActivePdf } from "./runner";
import {
  DEFAULT_SETTINGS,
  PdfFontRewriterSettingTab,
  type PdfFontRewriterSettings,
} from "./settings";

export default class PdfFontRewriterPlugin extends Plugin {
  settings: PdfFontRewriterSettings = DEFAULT_SETTINGS;

  async onload(): Promise<void> {
    await this.loadSettings();

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
        rewriteActivePdf(this, file).catch((error: unknown) => {
          console.error(error);
        });
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

    this.addSettingTab(new PdfFontRewriterSettingTab(this.app, this));
  }

  async loadSettings(): Promise<void> {
    const loaded = (await this.loadData()) as unknown;
    const savedSettings = isSettingsRecord(loaded) ? loaded : {};
    this.settings = { ...DEFAULT_SETTINGS, ...savedSettings };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }
}

function isSettingsRecord(value: unknown): value is Partial<PdfFontRewriterSettings> {
  return typeof value === "object" && value !== null;
}
