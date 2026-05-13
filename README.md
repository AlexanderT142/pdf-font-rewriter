# PDF Font Rewriter

Conservative Python CLI for rewriting safely replaceable PDF text into a target font while leaving image-only, rotated, unsupported, or geometrically unsafe content unchanged.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python -m refont INPUT.pdf --font /path/to/Font.ttf
python -m refont INPUT.pdf --font /path/to/Font.ttf --dry-run
python -m refont INPUT.pdf --font /path/to/Font.ttf --pages 1-10,15 --verbose
```

Outputs default to `INPUT_refonted.pdf` and `INPUT_refonted_audit.json`.

For Chinese PDFs, pass a fallback explicitly when possible:

```bash
python -m refont chinese.pdf \
  --font /path/to/LatinFont.ttf \
  --cjk-fallback /path/to/NotoSansCJKsc-Regular.otf
```

On macOS the tool also tries common system CJK fonts if `--cjk-fallback` is omitted.

## Current MVP Boundaries

- Native and searchable-scan hybrid pages are supported when they contain a clean visible text layer.
- The tool is not a general OCR engine. On hybrid pages it can validate and correct narrow high-confidence text-layer confusions, such as bracket/digit citation errors, against the scanned pixels before font replacement.
- Conservative skip behavior for image-only scanned, RTL, vertical, rotated, widget, missing-glyph, bad-Unicode, unresolved suspicious OCR, or bad-fit content.
- Browser preview is accepted as a CLI flag but not implemented yet.
- Bold/italic matching and form-field text rewriting are out of scope for v1.

## Obsidian Packaging

The Obsidian plugin is a desktop UI shell in `obsidian-plugin/`. It calls a packaged helper binary built from this Python engine, so end users do not need to install Python.

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

GitHub tag releases are handled by `.github/workflows/release.yml`. A `v0.1.0` tag builds:

- `refont-helper-macos-arm64`
- `refont-helper-macos-x64`
- `refont-helper-windows-x64.exe`
- `refont-helper-linux-x64`
- `helper-manifest.json`
- Obsidian `main.js`, `manifest.json`, and `styles.css`
