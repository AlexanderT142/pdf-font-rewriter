# PDF Font Rewriter for Obsidian

Desktop-only Obsidian plugin shell for PDF Font Rewriter.

The plugin calls the packaged `refont-helper` binary from the local app-data directory:

- macOS: `~/Library/Application Support/pdf-font-rewriter/bin/refont-helper`
- Windows: `%APPDATA%\pdf-font-rewriter\bin\refont-helper.exe`
- Linux: `~/.local/share/pdf-font-rewriter/bin/refont-helper`

On first conversion, the plugin downloads `helper-manifest.json`, selects the matching platform helper, verifies its SHA-256 hash, and installs it into that app-data path.

## Build

```bash
npm install
npm run build
```

The Obsidian release assets are:

- `main.js`
- `manifest.json`
- `styles.css`
