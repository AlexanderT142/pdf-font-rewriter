import type PdfFontRewriterPlugin from "./main";
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
  targetFontPath: string;
  cjkFallbackPath: string;
  outputSuffix: string;
  mode: "conservative" | "normal";
}

export const DEFAULT_SETTINGS: PdfFontRewriterSettings = {
  helperPath: defaultHelperPath(),
  helperReleaseBaseUrl: DEFAULT_HELPER_RELEASE_BASE_URL,
  helperVersion: "",
  helperPlatform: "",
  helperSha256: "",
  targetFontPath: "",
  cjkFallbackPath: "",
  outputSuffix: "_refonted",
  mode: "conservative",
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

    new Setting(containerEl)
      .setName("Helper binary path")
      .setDesc("Path to the packaged refont helper executable.")
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
      .setDesc("Base URL containing helper-manifest.json and helper binary assets.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_HELPER_RELEASE_BASE_URL)
          .setValue(this.plugin.settings.helperReleaseBaseUrl)
          .onChange(async (value) => {
            this.plugin.settings.helperReleaseBaseUrl = value.trim();
            await this.plugin.saveSettings();
          }),
      );

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
      .setName("Target font path")
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

    new Setting(containerEl)
      .setName("CJK fallback font path")
      .setDesc("Optional absolute path to a CJK fallback font.")
      .addText((text) =>
        text
          .setPlaceholder("/path/to/cjk-font.otf")
          .setValue(this.plugin.settings.cjkFallbackPath)
          .onChange(async (value) => {
            this.plugin.settings.cjkFallbackPath = value.trim();
            await this.plugin.saveSettings();
          }),
      );

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
  }
}
