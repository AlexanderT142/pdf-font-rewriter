# PDF Font Rewriter

Change the font inside a PDF from Obsidian without retyping it.

PDF Font Rewriter redraws safely replaceable PDF text in the font you choose. It is useful for papers, handouts, exported documents, and scanned PDFs that still have a searchable text layer.

By default it writes a new PDF next to the original. You can also choose **Replace current PDF** if you want the same file to be updated after a successful rewrite.

It does not live-edit the PDF viewer page like an ebook reader. The rewrite happens as a file conversion, then Obsidian opens or reopens the result when the rewrite finishes.

It does not try to guess everything. If a page is image-only, rotated, too uncertain, or unsafe to redraw cleanly, the plugin leaves that part unchanged.

![Before and after example on a searchable scanned PDF](https://raw.githubusercontent.com/AlexanderT142/pdf-font-rewriter/main/docs/assets/socialsystem-current-before-after.png)

![Original, serif rewrite, and two sans-serif rewrites](https://raw.githubusercontent.com/AlexanderT142/pdf-font-rewriter/main/docs/assets/socialsystem-current-font-grid.png)

## How To Use It

1. Install **PDF Font Rewriter** from Obsidian Community plugins.
2. Open a PDF in Obsidian.
3. Click the **PDF Font Rewriter** ribbon icon, right-click the PDF and choose **Rewrite PDF font**, or run **PDF Font Rewriter: Rewrite active PDF font** from the command palette.
4. Choose one of the built-in fonts, or choose **Custom font path** if you want to use your own `.ttf` or `.otf` file.
5. Choose whether to create a separate PDF or replace the current PDF.
6. Leave **Pages to rewrite** blank for the whole PDF, or enter PDF sheet numbers like `1-3,8` for a quick preview. These are the sheet numbers Obsidian shows as `330 / 683`, not always the printed page labels inside the book.
7. Click **Rewrite PDF**.

When text is changed, the plugin either writes a rewritten PDF next to the original PDF or replaces the current PDF, depending on the save option you chose. If the selected pages cannot be changed safely, it does not keep an unchanged output PDF.

Obsidian users do not need Python or Python dependencies. The plugin installs its packaged desktop helper automatically.

Built-in fonts include Libertinus Serif, Source Serif 4, Libre Baskerville, PT Serif, Libertinus Sans, Atkinson Hyperlegible, Fira Sans, and Work Sans.

## What It Works Best On

- PDFs with selectable text
- scanned PDFs where the text is still searchable/selectable
- documents where you want the words preserved but the typeface changed
- conservative partial conversion, where uncertain text should be left alone

## What It Does Not Do

- It is not a full OCR app.
- It does not rewrite pure image-only scans.
- It skips text when the replacement would not fit safely.
- It skips unsupported, rotated, vertical, RTL, form-field, or missing-glyph text.

## Privacy And Files

PDF Font Rewriter runs locally on your computer. It reads the selected PDF and selected font, then writes the rewritten PDF into your vault or replaces the selected PDF if you choose that mode. Technical audit reports are stored in the plugin's local app-data folder, not next to your PDF.

The plugin does not upload PDFs, fonts, or audit reports to any remote service.

Network use is limited to downloading or updating the desktop helper from this repository's GitHub Releases. The built-in fonts are bundled with the plugin and do not need a separate download. The helper download is selected for your OS/CPU platform and verified with SHA-256 before installation.

PDF Font Rewriter is desktop-only. It does not support Obsidian mobile.

## For People Who Are Technical

### Current Boundaries

- Native PDFs and searchable-scan hybrid PDFs are supported when they contain a clean visible text layer.
- On hybrid scanned pages, the tool can validate and correct narrow high-confidence text-layer confusions, such as bracket/digit citation errors, against the scanned pixels before font replacement.
- Conservative skip behavior applies to image-only scanned, RTL, vertical, rotated, widget, missing-glyph, bad-Unicode, unresolved suspicious OCR, or bad-fit content.
- The rewrite engine processes selected pages and saves the PDF at the end. Replace mode writes to a temporary file first and overwrites the current PDF only after a successful conversion. It does not replace Obsidian's built-in PDF renderer or stream page changes into the currently open viewer.
- Browser preview is accepted as a CLI flag but not implemented yet.
- Bold/italic matching and form-field text rewriting are out of scope for v1.

### Helper Install Location

- macOS: `~/Library/Application Support/pdf-font-rewriter/bin/refont-helper`
- Windows: `%APPDATA%\pdf-font-rewriter\bin\refont-helper.exe`
- Linux: `~/.local/share/pdf-font-rewriter/bin/refont-helper`

### Built-In Font Location

The plugin writes bundled fonts on demand into:

- macOS: `~/Library/Application Support/pdf-font-rewriter/fonts`
- Windows: `%APPDATA%\pdf-font-rewriter\fonts`
- Linux: `~/.local/share/pdf-font-rewriter/fonts`

### Python CLI

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

### Obsidian Packaging

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

GitHub tag releases are handled by `.github/workflows/release.yml`. A release tag builds:

- `refont-helper-macos-arm64`
- `refont-helper-macos-x64`
- `refont-helper-windows-x64.exe`
- `refont-helper-linux-x64`
- `helper-manifest.json`
- Obsidian `main.js`, `manifest.json`, and `styles.css`

## License

Apache-2.0. See `LICENSE`.

Bundled fonts are distributed under the SIL Open Font License 1.1. Source and license details are in `obsidian-plugin/fonts/README.md` and `obsidian-plugin/fonts/licenses/`.
