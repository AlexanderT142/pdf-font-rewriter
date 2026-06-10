# PDF Font Rewriter for Obsidian

Desktop-only Obsidian plugin shell for PDF Font Rewriter.

The plugin calls the packaged `refont-helper` binary from the local app-data directory:

- macOS: `~/Library/Application Support/pdf-font-rewriter/bin/refont-helper`
- Windows: `%APPDATA%\pdf-font-rewriter\bin\refont-helper.exe`
- Linux: `~/.local/share/pdf-font-rewriter/bin/refont-helper`

On activation, the plugin downloads `font-manifest.json`, verifies the built-in font SHA-256 hashes, and installs the font files into local app-data. Users can also import a local `.ttf` or `.otf` from the Live Refont toolbar, the settings tab, or the export dialog; the plugin copies imported fonts into the same local app-data tree under `custom-fonts` and stores the copied path in settings. On first conversion, it downloads `helper-manifest.json`, selects the matching platform helper, verifies its SHA-256 hash, and installs it into that app-data path. For local development, leave the helper release URL blank and point the helper binary path at a manually installed `refont-helper`.

The classic rewrite command reads the selected PDF and configured font files, then writes a rewritten PDF into the vault when text is changed. By default it creates a separate PDF; users can opt into replacing the current PDF after a successful rewrite. Replace mode saves the first restore copy for that PDF outside the vault before overwriting the same file path. Technical audit reports are stored in the plugin's local app-data folder. It opens or reopens the exported result when conversion finishes. It does not upload PDFs, fonts, backups, or audit reports to any remote service. Network use is limited to downloading or updating verified font assets and the helper from GitHub Releases.

## Experimental Live Refont View

The plugin also includes an experimental `Live Refont View`. This is the first implementation step toward scroll-time refonting: it registers a custom Obsidian view, renders PDF pages with PDF.js, owns the scroll container, and keeps a PDF.js text layer for selection. It asks the helper for page-level refont plans, renders a hidden text-suppressed PDF.js canvas, patches approved text pixels from that textless render, and draws replacement text on an overlay canvas. The live planner has an export-safe tier plus a live-fallback tier for pages whose text is extractable but fails export-grade scale checks; the compositor still validates those regions with the textless pixel diff before drawing. The toolbar reports checked pages and any pages left original-only. The Python helper now also has `live-plan` and `live-server` entry points for page-level refont plans instead of finished output PDFs.

Use the command palette action `Open active PDF in Live Refont View`, or right-click a PDF and choose `Open in Live Refont View`. The Live Refont toolbar includes a `Font` dropdown for built-in target fonts and an `Import` button for custom `.ttf` or `.otf` files; changing the target font rebuilds the live planner and rerenders the visible pages without mutating the original PDF. The settings page has an opt-in toggle for opening PDFs with this view by default; changing that toggle requires reloading Obsidian because file-extension view registration happens at plugin load.

## Build

```bash
npm install
npm run build
```

The Obsidian release assets are:

- `main.js`
- `manifest.json`
- `styles.css`
