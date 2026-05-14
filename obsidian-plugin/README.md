# PDF Font Rewriter for Obsidian

Desktop-only Obsidian plugin shell for PDF Font Rewriter.

The plugin calls the packaged `refont-helper` binary from the local app-data directory:

- macOS: `~/Library/Application Support/pdf-font-rewriter/bin/refont-helper`
- Windows: `%APPDATA%\pdf-font-rewriter\bin\refont-helper.exe`
- Linux: `~/.local/share/pdf-font-rewriter/bin/refont-helper`

On first conversion, the plugin downloads `helper-manifest.json`, selects the matching platform helper, verifies its SHA-256 hash, and installs it into that app-data path.

The plugin reads the selected PDF and configured font files, then writes a rewritten PDF and audit JSON file into the vault. It opens the rewritten PDF when conversion finishes; it does not live-edit Obsidian's built-in PDF viewer page. It does not upload PDFs, fonts, or audit output to any remote service. Network use is limited to downloading or updating the helper from GitHub Releases.

## Build

```bash
npm install
npm run build
```

The Obsidian release assets are:

- `main.js`
- `manifest.json`
- `styles.css`
