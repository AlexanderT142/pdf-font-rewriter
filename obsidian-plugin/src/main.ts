import { Notice, Plugin, TAbstractFile, TFile } from "obsidian";

import { isBuiltinFontId } from "./builtinFonts";
import { DEFAULT_HELPER_RELEASE_BASE_URL } from "./helperRelease";
import { installOrUpdateHelper } from "./helperInstaller";
import { PdfRewriteModal } from "./rewriteModal";
import { restoreActivePdfOriginal } from "./runner";
import {
  DEFAULT_SETTINGS,
  PdfFontRewriterSettingTab,
  type PdfOriginalBackup,
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

    this.addCommand({
      id: "restore-active-pdf-original",
      name: "Restore active PDF from backup",
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
        restoreActivePdfOriginal(this, file).catch((error: unknown) => {
          console.error(error);
        });
        return true;
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

        menu.addItem((item) => {
          item
            .setTitle("Restore original PDF")
            .setIcon("rotate-ccw")
            .onClick(() => {
              restoreActivePdfOriginal(this, file).catch((error: unknown) => {
                console.error(error);
              });
            });
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
    if (!isPageScope(savedSettings.pageScope)) {
      this.settings.pageScope = this.settings.pageRange.trim()
        ? "custom"
        : DEFAULT_SETTINGS.pageScope;
      migrated = true;
    }
    if (
      !Number.isInteger(savedSettings.visiblePageRadius) ||
      this.settings.visiblePageRadius < 0
    ) {
      this.settings.visiblePageRadius = DEFAULT_SETTINGS.visiblePageRadius;
      migrated = true;
    }
    if (this.settings.visiblePageRadius > 2) {
      this.settings.visiblePageRadius = 2;
      migrated = true;
    }
    if (Array.isArray(savedSettings.backups)) {
      this.settings.backups = savedSettings.backups.filter(isBackupRecord).slice(0, 50);
      if (this.settings.backups.length !== savedSettings.backups.length) {
        migrated = true;
      }
    } else {
      this.settings.backups = [];
      if (Object.prototype.hasOwnProperty.call(savedSettings, "backups")) {
        migrated = true;
      }
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

function isPageScope(value: unknown): value is PdfFontRewriterSettings["pageScope"] {
  return value === "visible-window" || value === "custom" || value === "all";
}

function isBackupRecord(value: unknown): value is PdfOriginalBackup {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Partial<PdfOriginalBackup>;
  return (
    typeof record.vaultPath === "string" &&
    typeof record.backupPath === "string" &&
    typeof record.createdAt === "string" &&
    typeof record.sourceSize === "number" &&
    typeof record.sourceMtimeMs === "number"
  );
}

function shouldMigrateHelperReleaseUrl(value: unknown): boolean {
  if (typeof value !== "string" || !value.trim()) {
    return true;
  }

  return /^https:\/\/github\.com\/AlexanderT142\/pdf-font-rewriter\/releases\/download\/v?\d+\.\d+\.\d+$/.test(
    value.trim(),
  );
}
