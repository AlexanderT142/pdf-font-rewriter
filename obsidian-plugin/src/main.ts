import { Notice, Plugin, TAbstractFile, TFile } from "obsidian";

import { installOrUpdateBuiltinFonts, isBuiltinFontId } from "./builtinFonts";
import { DEFAULT_HELPER_RELEASE_BASE_URL } from "./helperRelease";
import { installOrUpdateHelper } from "./helperInstaller";
import { LIVE_REFONT_VIEW_TYPE, LiveRefontPdfView, openLiveRefontView } from "./liveRefontView";
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

    this.registerView(LIVE_REFONT_VIEW_TYPE, (leaf) => new LiveRefontPdfView(leaf, this));
    if (this.settings.openPdfWithLiveView) {
      this.registerExtensions(["pdf"], LIVE_REFONT_VIEW_TYPE);
    }

    this.addRibbonIcon("type", "Open PDF in Live Refont View", () => {
      this.openLiveRefontViewForActiveFile();
    }).addClass("pdf-font-rewriter-ribbon-icon");

    this.addCommand({
      id: "rewrite-active-pdf-font",
      name: "Export active PDF with refonted text",
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
      id: "open-active-pdf-live-refont-view",
      name: "Open active PDF in Live Refont View",
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
        openLiveRefontView(this, file).catch((error: unknown) => {
          console.error(error);
        });
        return true;
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
            .setTitle("Open in Live Refont View")
            .setIcon("scan-text")
            .onClick(() => {
              openLiveRefontView(this, file).catch((error: unknown) => {
                console.error(error);
              });
            });
        });
      }),
    );

    this.addSettingTab(new PdfFontRewriterSettingTab(this.app, this));

    installOrUpdateBuiltinFonts(this).catch((error: unknown) => {
      console.warn("PDF Font Rewriter: built-in font install failed.", error);
    });
  }

  async loadSettings(): Promise<void> {
    const loaded = (await this.loadData()) as unknown;
    const savedSettings = isSettingsRecord(loaded) ? loaded : {};
    this.settings = { ...DEFAULT_SETTINGS, ...savedSettings };
    this.settings.builtinFontSha256 = isStringRecord(savedSettings.builtinFontSha256)
      ? { ...savedSettings.builtinFontSha256 }
      : {};
    let migrated = false;

    if (!Object.prototype.hasOwnProperty.call(savedSettings, "targetFontSource")) {
      this.settings.targetFontSource = this.settings.targetFontPath ? "custom" : "builtin";
      migrated = true;
    }
    if (!this.settings.builtinFontId || !isBuiltinFontId(this.settings.builtinFontId)) {
      this.settings.builtinFontId = DEFAULT_SETTINGS.builtinFontId;
      migrated = true;
    }
    if (typeof savedSettings.builtinFontsVersion !== "string") {
      this.settings.builtinFontsVersion = DEFAULT_SETTINGS.builtinFontsVersion;
      migrated = true;
    }
    if (!isStringRecord(savedSettings.builtinFontSha256)) {
      migrated = true;
    }
    if (this.settings.outputMode !== "copy" && this.settings.outputMode !== "replace") {
      this.settings.outputMode = DEFAULT_SETTINGS.outputMode;
      migrated = true;
    }
    if (typeof savedSettings.openPdfWithLiveView !== "boolean") {
      this.settings.openPdfWithLiveView = DEFAULT_SETTINGS.openPdfWithLiveView;
      migrated = true;
    }
    if (typeof savedSettings.liveRefontEnabled !== "boolean") {
      this.settings.liveRefontEnabled = DEFAULT_SETTINGS.liveRefontEnabled;
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

  openLiveRefontViewForActiveFile(): void {
    const file = this.app.workspace.getActiveFile();
    if (!isPdfFile(file)) {
      new Notice("PDF Font Rewriter: open a PDF file first.");
      return;
    }

    openLiveRefontView(this, file).catch((error: unknown) => {
      console.error(error);
    });
  }
}

function isSettingsRecord(value: unknown): value is Partial<PdfFontRewriterSettings> {
  return typeof value === "object" && value !== null;
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every((entry) => typeof entry === "string")
  );
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
  if (typeof value !== "string") {
    return true;
  }

  const trimmed = value.trim();
  if (!trimmed || trimmed === DEFAULT_HELPER_RELEASE_BASE_URL) {
    return false;
  }

  return /^https:\/\/github\.com\/AlexanderT142\/pdf-font-rewriter\/releases\/download\/v?\d+\.\d+\.\d+$/.test(
    trimmed,
  );
}
