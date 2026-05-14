import { ButtonComponent, Modal, Notice, Setting, TFile } from "obsidian";

import {
  BUILTIN_FONTS,
  CUSTOM_FONT_ID,
} from "./builtinFonts";
import type PdfFontRewriterPlugin from "./main";
import { rewriteActivePdf } from "./runner";
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
    contentEl.empty();
    contentEl.addClass("pdf-font-rewriter-modal");

    new Setting(contentEl).setName("Rewrite PDF font").setHeading();
    contentEl.createEl("p", {
      text: `File: ${this.file.path}`,
      cls: "pdf-font-rewriter-muted",
    });

    new Setting(contentEl)
      .setName("Target font")
      .setDesc("Built-in fonts work immediately. Choose custom to use your own .ttf or .otf file.")
      .addDropdown((dropdown) => {
        for (const font of BUILTIN_FONTS) {
          dropdown.addOption(font.id, font.label);
        }

        return dropdown
          .addOption(CUSTOM_FONT_ID, "Custom font path")
          .setValue(
            this.plugin.settings.targetFontSource === "custom"
              ? CUSTOM_FONT_ID
              : this.plugin.settings.builtinFontId,
          )
          .onChange(async (value) => {
            if (value === CUSTOM_FONT_ID) {
              this.plugin.settings.targetFontSource = "custom";
            } else {
              this.plugin.settings.targetFontSource = "builtin";
              this.plugin.settings.builtinFontId = value;
            }
            await this.plugin.saveSettings();
            this.display();
          });
      });

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

    new Setting(contentEl)
      .setName("Pages to rewrite")
      .setDesc('Blank rewrites the whole PDF. Use pages like "1-3,8" for a quick preview.')
      .addText((text) =>
        text
          .setPlaceholder("all pages")
          .setValue(this.plugin.settings.pageRange)
          .onChange(async (value) => {
            this.plugin.settings.pageRange = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(contentEl)
      .setName("Open rewritten PDF")
      .setDesc("Switch to the new PDF after conversion finishes.")
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
      .setButtonText("Rewrite PDF")
      .setCta()
      .onClick(() => {
        if (
          this.plugin.settings.targetFontSource === "custom" &&
          !this.plugin.settings.targetFontPath.trim()
        ) {
          new Notice("PDF Font Rewriter: enter a custom font path first.");
          return;
        }

        this.close();
        rewriteActivePdf(this.plugin, this.file).catch((error: unknown) => {
          console.error(error);
        });
      });
  }
}
