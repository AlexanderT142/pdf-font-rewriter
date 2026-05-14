# PDF Font Rewriter

Change the font inside a PDF from Obsidian without retyping it.

PDF Font Rewriter redraws safely replaceable PDF text in the font you choose. It is useful for papers, handouts, exported documents, and scanned PDFs that still have a searchable text layer.

By default it writes a new PDF next to the original. You can also choose **Replace current PDF** if you want the same file path to be updated after a successful rewrite.

For smoother reading, the plugin also includes an experimental **Live Refont View**. It opens a PDF in the plugin's own PDF.js view, plans each visible page with the local helper, erases approved original text pixels using a hidden textless render, and draws replacement text as you scroll. The original PDF remains the source of truth; exporting a rewritten PDF is still a separate action.

It does not try to guess everything. If a page is image-only, rotated, too uncertain, or unsafe to redraw cleanly, the plugin leaves that part unchanged.

![Before and after example on a searchable scanned PDF](https://raw.githubusercontent.com/AlexanderT142/pdf-font-rewriter/main/docs/assets/socialsystem-current-before-after.png)

![Original, serif rewrite, and two sans-serif rewrites](https://raw.githubusercontent.com/AlexanderT142/pdf-font-rewriter/main/docs/assets/socialsystem-current-font-grid.png)

## How To Use It

1. Install **PDF Font Rewriter** from Obsidian Community plugins.
2. Open a PDF in Obsidian.
3. Click the **PDF Font Rewriter** ribbon icon, right-click the PDF and choose **Rewrite PDF font**, or run **PDF Font Rewriter: Rewrite active PDF font** from the command palette.
4. Choose one of the built-in fonts, or choose **Custom font path** if you want to use your own `.ttf` or `.otf` file.
5. Choose whether to create a separate PDF or replace the current PDF.
6. For live reading, run **PDF Font Rewriter: Open active PDF in Live Refont View** from the command palette, or right-click a PDF and choose **Open in Live Refont View**.
7. To export a rewritten PDF instead, leave the scope on **Visible page + nearby pages** for normal reading, then click **Rewrite visible pages**. It rewrites the PDF sheet Obsidian is showing, plus the nearby sheets you choose, without using the printed page label inside the book.

When text is changed, the plugin either writes a rewritten PDF next to the original PDF or replaces the current PDF, depending on the save option you chose. In replace mode, it first saves a restore copy outside the vault, then overwrites the same PDF path only after conversion succeeds. If the selected pages cannot be changed safely, it does not keep an unchanged output PDF.

Obsidian users do not need Python or Python dependencies. The plugin installs its packaged desktop helper automatically.

Built-in fonts include Charis SIL, XCharter, TeX Gyre Pagella, EB Garamond, Inter, Noto Sans, Open Sans, Lato, Atkinson Hyperlegible, Andika, and OpenDyslexic.

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

When **Replace current PDF** is used, the plugin keeps the first restore copy for that PDF outside the vault so the original file can be restored from the command palette or the rewrite dialog.

The plugin does not upload PDFs, fonts, or audit reports to any remote service.

Network use is limited to downloading or updating the desktop helper from this repository's GitHub Releases. The built-in fonts are bundled with the plugin and do not need a separate download. The helper download is selected for your OS/CPU platform and verified with SHA-256 before installation.

PDF Font Rewriter is desktop-only. It does not support Obsidian mobile.

## For People Who Are Technical

### Current Boundaries

- Native PDFs and searchable-scan hybrid PDFs are supported when they contain a clean visible text layer.
- On hybrid scanned pages, the tool can validate and correct narrow high-confidence text-layer confusions, such as bracket/digit citation errors, against the scanned pixels before font replacement.
- Conservative skip behavior applies to image-only scanned, RTL, vertical, rotated, widget, missing-glyph, bad-Unicode, unresolved suspicious OCR, or bad-fit content.
- The classic rewrite engine processes selected pages and saves the PDF at the end. Replace mode writes to a temporary file first and overwrites the current PDF only after a successful conversion.
- Live Refont View is a separate custom PDF.js view. It does not mutate the source PDF while reading; it renders refonted pages in place and leaves export as a separate action.
- The normal Obsidian workflow targets the visible PDF sheet plus nearby sheets. Manual sheet ranges and whole-PDF rewrites are still available for technical use.
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

Bundled fonts are open-license fonts. Source and license details are in `obsidian-plugin/fonts/README.md` and `obsidian-plugin/fonts/licenses/`.
