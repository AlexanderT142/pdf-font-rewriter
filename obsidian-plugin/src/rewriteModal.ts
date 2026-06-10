import { ButtonComponent, Modal, Notice, Setting, TFile } from "obsidian";

import { CUSTOM_FONT_ID } from "./builtinFonts";
import {
  applyTargetFontSelection,
  importCustomFont,
  targetFontOptions,
  targetFontSelectValue,
} from "./fontSelection";
import type PdfFontRewriterPlugin from "./main";
import { restoreActivePdfOriginal, rewriteActivePdf } from "./runner";
import type { PdfFontRewriterSettings } from "./settings";

export class PdfRewriteModal extends Modal {
  private plugin: PdfFontRewriterPlugin;
  private file: TFile;

  constructor(plugin: PdfFontRewriterPlugin, file: TFile) {
    super(plugin.app);
    this.plugin = plugin;
    this.file = file;
  }

  onOpen(): void {
    this.display();
  }

  private display(): void {
    const { contentEl } = this;
    const currentSheet = detectCurrentPdfSheetPosition(this.plugin, this.file);
    contentEl.empty();
    contentEl.addClass("pdf-font-rewriter-modal");

    new Setting(contentEl).setName("Rewrite PDF font").setHeading();
    contentEl.createEl("p", {
      text: `File: ${this.file.path}`,
      cls: "pdf-font-rewriter-muted",
    });

    new Setting(contentEl)
      .setName("Target font")
      .setDesc("Built-in fonts install automatically. Choose custom to use your own .ttf or .otf file.")
      .addDropdown((dropdown) => {
        for (const option of targetFontOptions(this.plugin.settings, { includeCustomPath: true })) {
          dropdown.addOption(option.value, option.label);
        }

        return dropdown
          .setValue(targetFontSelectValue(this.plugin.settings))
          .onChange(async (value) => {
            await applyTargetFontSelection(this.plugin, value);
            this.display();
          });
      })
      .addButton((button) =>
        button.setButtonText("Import .ttf/.otf").onClick(async () => {
          button.setDisabled(true);
          try {
            await importCustomFont(this.plugin);
            this.display();
          } catch (error) {
            console.error(error);
            new Notice("PDF Font Rewriter: could not import that font.");
          } finally {
            button.setDisabled(false);
          }
        }),
      );

    if (this.plugin.settings.targetFontSource === "custom") {
      new Setting(contentEl)
        .setName("Custom font path")
        .setDesc("Absolute path to the .ttf or .otf font file.")
        .addText((text) =>
          text
            .setPlaceholder("/path/to/font.ttf")
            .setValue(this.plugin.settings.targetFontPath)
            .onChange(async (value) => {
              this.plugin.settings.targetFontPath = value.trim();
              await this.plugin.saveSettings();
            }),
        );
    }

    new Setting(contentEl)
      .setName("Mode")
      .setDesc("Conservative keeps more original content unchanged when a rewrite looks risky.")
      .addDropdown((dropdown) =>
        dropdown
          .addOption("conservative", "Conservative")
          .addOption("normal", "Normal")
          .setValue(this.plugin.settings.mode)
          .onChange(async (value) => {
            this.plugin.settings.mode = value as PdfFontRewriterSettings["mode"];
            await this.plugin.saveSettings();
          }),
      );

    new Setting(contentEl)
      .setName("Save result")
      .setDesc(
        "Create a separate PDF by default, or replace this PDF after the rewrite succeeds.",
      )
      .addDropdown((dropdown) =>
        dropdown
          .addOption("copy", "Create a separate PDF")
          .addOption("replace", "Replace current PDF")
          .setValue(this.plugin.settings.outputMode)
          .onChange(async (value) => {
            this.plugin.settings.outputMode = value as PdfFontRewriterSettings["outputMode"];
            await this.plugin.saveSettings();
            this.display();
          }),
      );

    if (this.plugin.settings.outputMode === "copy") {
      new Setting(contentEl)
        .setName("Output suffix")
        .setDesc("The rewritten PDF is saved next to the original.")
        .addText((text) =>
          text
            .setPlaceholder("_refonted")
            .setValue(this.plugin.settings.outputSuffix)
            .onChange(async (value) => {
              this.plugin.settings.outputSuffix = value.trim() || "_refonted";
              await this.plugin.saveSettings();
            }),
        );
    }

    new Setting(contentEl)
      .setName("Scope")
      .setDesc(scopeDescription(this.plugin.settings, currentSheet))
      .addDropdown((dropdown) =>
        dropdown
          .addOption("visible-window", "Visible page + nearby pages")
          .addOption("custom", "Custom PDF sheet numbers")
          .addOption("all", "Whole PDF")
          .setValue(this.plugin.settings.pageScope)
          .onChange(async (value) => {
            this.plugin.settings.pageScope = value as PdfFontRewriterSettings["pageScope"];
            await this.plugin.saveSettings();
            this.display();
          }),
      );

    if (this.plugin.settings.pageScope === "visible-window") {
      new Setting(contentEl)
        .setName("Nearby pages")
        .setDesc("Rewrite the visible sheet plus this many sheets before and after it.")
        .addDropdown((dropdown) =>
          dropdown
            .addOption("0", "Visible page only")
            .addOption("1", "One page before and after")
            .addOption("2", "Two pages before and after")
            .setValue(String(this.plugin.settings.visiblePageRadius))
            .onChange(async (value) => {
              this.plugin.settings.visiblePageRadius = Number(value);
              await this.plugin.saveSettings();
              this.display();
            }),
        );
    }

    if (this.plugin.settings.pageScope === "custom") {
      new Setting(contentEl)
        .setName("Pages to rewrite")
        .setDesc(pageRangeDescription(currentSheet))
        .addText((text) =>
          text
            .setPlaceholder("1-3,8")
            .setValue(this.plugin.settings.pageRange)
            .onChange(async (value) => {
              this.plugin.settings.pageRange = value.trim();
              await this.plugin.saveSettings();
            }),
        )
        .addButton((button) =>
          button
            .setButtonText(
              currentSheet ? `Use visible page ${currentSheet.page}` : "Use visible page",
            )
            .setDisabled(currentSheet === null)
            .onClick(async () => {
              if (currentSheet === null) {
                return;
              }
              this.plugin.settings.pageRange = String(currentSheet.page);
              await this.plugin.saveSettings();
              this.display();
            }),
        );
    }

    new Setting(contentEl)
      .setName("Open result when finished")
      .setDesc("Switch to the new PDF, or reopen this PDF when using replace mode.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.openAfterRewrite)
          .onChange(async (value) => {
            this.plugin.settings.openAfterRewrite = value;
            await this.plugin.saveSettings();
          }),
      );

    const footer = contentEl.createDiv({ cls: "pdf-font-rewriter-modal-footer" });
    new ButtonComponent(footer)
      .setButtonText("Cancel")
      .onClick(() => this.close());

    new ButtonComponent(footer)
      .setButtonText("Restore original")
      .onClick(() => {
        this.close();
        restoreActivePdfOriginal(this.plugin, this.file).catch((error: unknown) => {
          console.error(error);
        });
      });

    new ButtonComponent(footer)
      .setButtonText(rewriteButtonText(this.plugin.settings))
      .setCta()
      .onClick(() => {
        const pageRange = pageRangeForScope(this.plugin.settings, currentSheet);
        if (pageRange === null) {
          return;
        }

        if (
          this.plugin.settings.targetFontSource === "custom" &&
          !this.plugin.settings.targetFontPath.trim()
        ) {
          new Notice("PDF Font Rewriter: enter a custom font path first.");
          return;
        }

        this.close();
        rewriteActivePdf(this.plugin, this.file, { pageRangeOverride: pageRange }).catch(
          (error: unknown) => {
            console.error(error);
          },
        );
      });
  }
}

interface PdfSheetPosition {
  page: number;
  total: number;
}

function scopeDescription(
  settings: PdfFontRewriterSettings,
  currentSheet: PdfSheetPosition | null,
): string {
  if (settings.pageScope === "all") {
    return "Rewrite every page. This can take much longer on large books.";
  }

  if (settings.pageScope === "custom") {
    return "Enter PDF sheet numbers when you need a precise manual range.";
  }

  if (currentSheet === null) {
    return "Open the PDF page you want to change. The plugin will use Obsidian's visible sheet number.";
  }

  const range = visibleWindowRange(currentSheet, settings.visiblePageRadius);
  return `Will rewrite PDF sheets ${range}. The printed page label may be different.`;
}

function pageRangeDescription(currentSheet: PdfSheetPosition | null): string {
  const base = 'Use PDF sheet numbers like "1-3,8", not printed book page labels.';
  if (currentSheet === null) {
    return base;
  }

  return `${base} The visible sheet is ${currentSheet.page}.`;
}

function pageRangeForScope(
  settings: PdfFontRewriterSettings,
  currentSheet: PdfSheetPosition | null,
): string | null {
  if (settings.pageScope === "all") {
    return "";
  }

  if (settings.pageScope === "custom") {
    if (!settings.pageRange.trim()) {
      new Notice("PDF Font Rewriter: enter pages to rewrite, or choose Whole PDF.");
      return null;
    }
    return settings.pageRange;
  }

  if (currentSheet === null) {
    new Notice("PDF Font Rewriter: could not detect the visible PDF sheet.");
    return null;
  }

  return visibleWindowRange(currentSheet, settings.visiblePageRadius);
}

function visibleWindowRange(currentSheet: PdfSheetPosition, radius: number): string {
  const safeRadius = Math.max(0, Math.min(2, Math.trunc(radius)));
  const start = Math.max(1, currentSheet.page - safeRadius);
  const end = Math.min(currentSheet.total, currentSheet.page + safeRadius);
  return start === end ? String(start) : `${start}-${end}`;
}

function rewriteButtonText(settings: PdfFontRewriterSettings): string {
  if (settings.pageScope === "visible-window") {
    return "Rewrite visible pages";
  }

  if (settings.pageScope === "custom") {
    return "Rewrite selected pages";
  }

  return settings.outputMode === "replace" ? "Rewrite current PDF" : "Rewrite PDF";
}

function detectCurrentPdfSheetPosition(
  plugin: PdfFontRewriterPlugin,
  file: TFile,
): PdfSheetPosition | null {
  const activeFile = plugin.app.workspace.getActiveFile();
  const activeLeaf = plugin.app.workspace.getMostRecentLeaf();
  if (!activeFile || activeFile.path !== file.path || !activeLeaf) {
    return null;
  }

  const text = activeLeaf.view.containerEl?.textContent ?? "";
  const match = /\((\d+)\s*\/\s*(\d+)\)/.exec(text);
  if (!match) {
    return null;
  }

  const page = Number(match[1]);
  const total = Number(match[2]);
  return Number.isInteger(page) && page > 0 && Number.isInteger(total) && total >= page
    ? { page, total }
    : null;
}
