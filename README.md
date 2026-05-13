# PDF Font Rewriter

Desktop-only Obsidian plugin for rewriting safely replaceable PDF text into a selected font while leaving image-only, rotated, unsupported, or geometrically unsafe content unchanged.

## Obsidian Usage

Install the plugin from Obsidian Community plugins, then open **Settings → PDF Font Rewriter** and set:

- **Target font path**: absolute path to a `.ttf` or `.otf` font.
- **CJK fallback font path**: optional absolute path to a CJK font for Chinese/Japanese/Korean PDFs.
- **Mode**: keep **Conservative** unless you want the helper to attempt more replacements.

Open a PDF in Obsidian and run **PDF Font Rewriter: Rewrite active PDF font** from the command palette. The plugin writes a rewritten PDF and an audit JSON file next to the original PDF in the vault.

Obsidian users do not need Python or Python dependencies. The plugin installs a packaged native helper automatically on desktop.

## Current MVP Boundaries

- Native and searchable-scan hybrid pages are supported when they contain a clean visible text layer.
- The tool is not a general OCR engine. On hybrid pages it can validate and correct narrow high-confidence text-layer confusions, such as bracket/digit citation errors, against the scanned pixels before font replacement.
- Conservative skip behavior for image-only scanned, RTL, vertical, rotated, widget, missing-glyph, bad-Unicode, unresolved suspicious OCR, or bad-fit content.
- Browser preview is accepted as a CLI flag but not implemented yet.
- Bold/italic matching and form-field text rewriting are out of scope for v1.

## Obsidian Plugin Disclosure

PDF Font Rewriter is desktop-only. It does not support Obsidian mobile.

The plugin downloads a native helper binary from this repository's GitHub Releases when the helper is missing or outdated. The downloaded helper is selected for the user's OS/CPU platform and verified against `helper-manifest.json` with SHA-256 before installation.

The helper is installed outside the vault:

- macOS: `~/Library/Application Support/pdf-font-rewriter/bin/refont-helper`
- Windows: `%APPDATA%\pdf-font-rewriter\bin\refont-helper.exe`
- Linux: `~/.local/share/pdf-font-rewriter/bin/refont-helper`

The plugin executes that helper locally to process PDFs. It reads the selected PDF and configured font files, then writes a rewritten PDF and an audit JSON file into the vault. The plugin does not upload PDFs, fonts, or audit output to any remote service.

Network use is limited to downloading/updating the helper from this repository's GitHub Releases.

## Python CLI

The same engine can be run directly as a Python CLI for development and advanced local use.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

```bash
python -m refont INPUT.pdf --font /path/to/Font.ttf
python -m refont INPUT.pdf --font /path/to/Font.ttf --dry-run
python -m refont INPUT.pdf --font /path/to/Font.ttf --pages 1-10,15 --verbose
```

CLI outputs default to `INPUT_refonted.pdf` and `INPUT_refonted_audit.json`.

For Chinese PDFs, pass a fallback explicitly when possible:

```bash
python -m refont chinese.pdf \
  --font /path/to/LatinFont.ttf \
  --cjk-fallback /path/to/NotoSansCJKsc-Regular.otf
```

On macOS the CLI also tries common system CJK fonts if `--cjk-fallback` is omitted.

## Obsidian Packaging

The Obsidian plugin is a desktop UI shell in `obsidian-plugin/`. It calls a packaged helper binary built from this Python engine.

Build the local helper:

```bash
uv sync --extra package
uv run python packaging/build_helper.py --clean
uv run python packaging/install_local_helper.py
```

Prepare helper release assets:

```bash
uv run python packaging/prepare_helper_release.py --clean
```

Build the Obsidian plugin:

```bash
cd obsidian-plugin
npm install
npm run build
```

Release artifacts are separated:

- Obsidian marketplace/plugin assets: `obsidian-plugin/main.js`, `obsidian-plugin/manifest.json`, `obsidian-plugin/styles.css`
- Helper release assets: `release/helper/helper-manifest.json`, `release/helper/refont-helper-<platform>`

GitHub tag releases are handled by `.github/workflows/release.yml`. A `0.1.2` tag builds:

- `refont-helper-macos-arm64`
- `refont-helper-macos-x64`
- `refont-helper-windows-x64.exe`
- `refont-helper-linux-x64`
- `helper-manifest.json`
- Obsidian `main.js`, `manifest.json`, and `styles.css`

## License

Apache-2.0. See `LICENSE`.
