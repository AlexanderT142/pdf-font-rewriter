import type PdfFontRewriterPlugin from "./main";
import {
  BUILTIN_FONTS,
  CUSTOM_FONT_ID,
  DEFAULT_BUILTIN_FONT_ID,
  installOrUpdateBuiltinFonts,
} from "./builtinFonts";
import { installOrUpdateHelper } from "./helperInstaller";
import { DEFAULT_HELPER_RELEASE_BASE_URL } from "./helperRelease";
import { defaultHelperPath } from "./platform";
import { App, PluginSettingTab, Setting } from "obsidian";

export interface PdfFontRewriterSettings {
  helperPath: string;
  helperReleaseBaseUrl: string;
  helperVersion: string;
  helperPlatform: string;
  helperSha256: string;
  targetFontSource: "builtin" | "custom";
  builtinFontId: string;
  builtinFontsVersion: string;
  builtinFontSha256: Record<string, string>;
  targetFontPath: string;
  cjkFallbackPath: string;
  outputMode: "copy" | "replace";
  outputSuffix: string;
  openPdfWithLiveView: boolean;
  pageScope: "visible-window" | "custom" | "all";
  visiblePageRadius: number;
  pageRange: string;
  openAfterRewrite: boolean;
  mode: "conservative" | "normal";
  backups: PdfOriginalBackup[];
}

export interface PdfOriginalBackup {
  vaultPath: string;
  backupPath: string;
  createdAt: string;
  sourceSize: number;
  sourceMtimeMs: number;
}

export const DEFAULT_SETTINGS: PdfFontRewriterSettings = {
  helperPath: defaultHelperPath(),
  helperReleaseBaseUrl: DEFAULT_HELPER_RELEASE_BASE_URL,
  helperVersion: "",
  helperPlatform: "",
  helperSha256: "",
  targetFontSource: "builtin",
  builtinFontId: DEFAULT_BUILTIN_FONT_ID,
  builtinFontsVersion: "",
  builtinFontSha256: {},
  targetFontPath: "",
  cjkFallbackPath: "",
  outputMode: "copy",
  outputSuffix: "_refonted",
  openPdfWithLiveView: false,
  pageScope: "visible-window",
  visiblePageRadius: 1,
  pageRange: "",
  openAfterRewrite: true,
  mode: "conservative",
  backups: [],
};

export class PdfFontRewriterSettingTab extends PluginSettingTab {
  plugin: PdfFontRewriterPlugin;

  constructor(app: App, plugin: PdfFontRewriterPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl).setName("Rewrite PDFs").setHeading();

    new Setting(containerEl)
      .setName("Target font")
      .setDesc("Choose a built-in font, or use a custom .ttf/.otf file below.")
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
      new Setting(containerEl)
        .setName("Custom font path")
        .setDesc("Absolute path to the .ttf or .otf font used for PDF rewriting.")
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

    new Setting(containerEl).setName("Built-in fonts").setHeading();

    const fontStatus = this.plugin.settings.builtinFontsVersion
      ? `Installed from release ${this.plugin.settings.builtinFontsVersion}`
      : "Will install after plugin activation, or on first use.";

    new Setting(containerEl)
      .setName("Font assets")
      .setDesc(fontStatus)
      .addButton((button) =>
        button.setButtonText("Install / update").onClick(async () => {
          button.setDisabled(true);
          try {
            await installOrUpdateBuiltinFonts(this.plugin, { notify: true });
            this.display();
          } catch (error) {
            console.error(error);
          } finally {
            button.setDisabled(false);
          }
        }),
      );

    new Setting(containerEl)
      .setName("Mode")
      .setDesc("Conservative mode skips more content when the geometry or glyph coverage is risky.")
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

    new Setting(containerEl)
      .setName("Save result")
      .setDesc("Create a separate PDF by default, or replace the current PDF after a successful rewrite.")
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
      new Setting(containerEl)
        .setName("Output suffix")
        .setDesc("Suffix added to rewritten PDFs.")
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

    new Setting(containerEl)
      .setName("Open PDFs with Live Refont View")
      .setDesc(
        "Experimental: use the plugin's PDF.js view for PDFs so live scroll-time refonting can run in-place. Reload Obsidian after changing this.",
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.openPdfWithLiveView)
          .onChange(async (value) => {
            this.plugin.settings.openPdfWithLiveView = value;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Default scope")
      .setDesc("For normal use, rewrite the visible PDF sheet and nearby sheets instead of the whole book.")
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
      new Setting(containerEl)
        .setName("Nearby pages")
        .setDesc("How many sheets before and after the visible sheet should be rewritten.")
        .addDropdown((dropdown) =>
          dropdown
            .addOption("0", "Visible page only")
            .addOption("1", "One page before and after")
            .addOption("2", "Two pages before and after")
            .setValue(String(this.plugin.settings.visiblePageRadius))
            .onChange(async (value) => {
              this.plugin.settings.visiblePageRadius = Number(value);
              await this.plugin.saveSettings();
            }),
        );
    }

    if (this.plugin.settings.pageScope === "custom") {
      new Setting(containerEl)
        .setName("Pages to rewrite")
        .setDesc(
          'Use PDF sheet numbers like "1-3,8". These are not always the printed page labels inside the book.',
        )
        .addText((text) =>
          text
            .setPlaceholder("1-3,8")
            .setValue(this.plugin.settings.pageRange)
            .onChange(async (value) => {
              this.plugin.settings.pageRange = value.trim();
              await this.plugin.saveSettings();
            }),
        );
    }

    new Setting(containerEl)
      .setName("Open result when finished")
      .setDesc("Open the new PDF, or reopen the current PDF when using replace mode.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.openAfterRewrite)
          .onChange(async (value) => {
            this.plugin.settings.openAfterRewrite = value;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("CJK fallback font path")
      .setDesc("Optional absolute path to a Chinese/Japanese/Korean fallback font.")
      .addText((text) =>
        text
          .setPlaceholder("/path/to/cjk-font.otf")
          .setValue(this.plugin.settings.cjkFallbackPath)
          .onChange(async (value) => {
            this.plugin.settings.cjkFallbackPath = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl).setName("Helper").setHeading();

    const helperStatus = this.plugin.settings.helperVersion
      ? `${this.plugin.settings.helperVersion} (${this.plugin.settings.helperPlatform})`
      : "Not installed by plugin yet";

    new Setting(containerEl)
      .setName("Helper status")
      .setDesc(helperStatus)
      .addButton((button) =>
        button.setButtonText("Install / update").onClick(async () => {
          button.setDisabled(true);
          try {
            await installOrUpdateHelper(this.plugin);
            this.display();
          } catch (error) {
            console.error(error);
          } finally {
            button.setDisabled(false);
          }
        }),
      );

    new Setting(containerEl)
      .setName("Helper binary path")
      .setDesc("Advanced: path to the packaged refont helper executable.")
      .addText((text) =>
        text
          .setPlaceholder(defaultHelperPath())
          .setValue(this.plugin.settings.helperPath)
          .onChange(async (value) => {
            this.plugin.settings.helperPath = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Helper release URL")
      .setDesc(
        "Advanced: base URL containing helper-manifest.json, font-manifest.json, and release assets. Leave blank to use the helper binary path directly.",
      )
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_HELPER_RELEASE_BASE_URL)
          .setValue(this.plugin.settings.helperReleaseBaseUrl)
          .onChange(async (value) => {
            this.plugin.settings.helperReleaseBaseUrl = value.trim();
            await this.plugin.saveSettings();
          }),
      );
  }
}
