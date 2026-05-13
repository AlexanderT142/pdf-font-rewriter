# PDF Font Rewriter — Build Spec

## What this is

A Python CLI tool that takes a native/generated PDF and a target font, and outputs a new PDF where all safely-replaceable text is rendered in the target font. Layout, images, diagrams, and all non-text elements remain untouched. Pages or regions that cannot be safely converted are left unchanged. An audit report is produced alongside the output PDF.

This is NOT a PDF viewer, NOT an OCR tool, NOT a universal PDF transformer. It is a conservative rewriter for ordinary reading documents (books, papers, reports, manuals) that prioritizes trust over coverage.

## Core product contract

- We convert safe native text to the user's chosen font.
- We leave unsafe content unchanged.
- We produce a report explaining what was converted and what was skipped, and why.
- We do not claim arbitrary-PDF perfection.
- The output PDF can be opened in any standard PDF reader (Preview, Acrobat, Zotero, PDF Expert, etc).

## Technology stack

- **Python 3.11+**
- **PyMuPDF (fitz)** — PDF parsing, text extraction, redaction, text insertion, font embedding
- **HarfBuzz** (via `uharfbuzz`) — text shaping for accurate metric calculation
- **Click** or **argparse** — CLI interface

Do NOT use: Tesseract, OCR libraries, OpenCV, or any image processing. Scanned PDFs are out of scope.

---

## Architecture

```
Input PDF + target font file (.ttf/.otf)
  │
  ▼
Page Classifier
  │  For each page: classify as native / scanned / hybrid / unknown
  │
  ▼
Native Text Extractor (skip non-native pages)
  │  Extract text runs with: text, bbox, transform, font, size, color, opacity, seqno
  │  Group runs into visual lines using baseline proximity + reading direction
  │
  ▼
Safety Analyzer
  │  For each line/run:
  │    - Check paint order: are there later non-text objects overlapping this text bbox?
  │    - Check if text is invisible OCR layer (render mode)
  │    - Check if Unicode extraction is reliable
  │    - Check if target font has glyph coverage (with fallback chain)
  │    - Check if replacement fits within original geometry (scaleX 0.85–1.15)
  │  Mark each line as: safe / unsafe (with reason)
  │
  ▼
Text Remover (safe lines only)
  │  Use PyMuPDF redaction API:
  │    - add_redact_annot() for each safe text region
  │    - apply_redactions() with images=PDF_REDACT_IMAGE_NONE, graphics=0, fill=False (no white rect)
  │  Snapshot and restore links that overlap redaction regions
  │
  ▼
Text Inserter (safe lines only)
  │  For each safe line:
  │    - Shape the full line text in target font using HarfBuzz
  │    - Compute fontSize from original line height, adjusted for target font metrics
  │    - Compute scaleX = originalAdvance / targetAdvance
  │    - If scaleX is within bounds: insert text at original baseline position
  │    - Embed the target font into the PDF
  │
  ▼
Output PDF + Audit Report (JSON + human-readable summary)
```

---

## Page Classification

For each page, determine its type:

```python
def classify_page(page) -> str:
    """Returns: 'native' | 'scanned' | 'hybrid' | 'unknown'"""
    text_dict = page.get_text("dict")
    has_native_text = any(
        span["text"].strip()
        for block in text_dict["blocks"] if block["type"] == 0
        for line in block["lines"]
        for span in line["spans"]
    )
    images = page.get_images()
    has_large_image = any(
        img_bbox_covers_most_of_page(page, img) for img in images
    )

    if has_native_text and not has_large_image:
        return "native"
    elif has_large_image and not has_native_text:
        return "scanned"
    elif has_large_image and has_native_text:
        return "hybrid"
    else:
        return "unknown"
```

Only `"native"` pages proceed to extraction. All others are copied unchanged to the output PDF.

---

## Text Extraction

Use PyMuPDF's `get_text("rawdict")` to get blocks → lines → spans → chars with:
- `text`: Unicode string
- `bbox`: (x0, y0, x1, y1) in PDF points
- `origin`: baseline origin point
- `font`: original font name
- `size`: original font size in points
- `color`: integer RGB
- `flags`: bold/italic/etc

Additionally, use `page.get_bboxlog()` to get the paint-order sequence of ALL objects (text, images, paths, shadings) on the page. Each entry has a type code and bbox. The index position IS the sequence number (seqno).

Also use `page.get_texttrace()` to get low-level span data including `seqno`, `opacity`, `dir` (writing direction), and render mode (visible vs invisible).

### Grouping runs into lines

Do NOT treat each span as an independent unit. Group spans into visual lines:

1. Sort spans by seqno (paint order).
2. Cluster spans whose baselines are within a tolerance (e.g., 2pt vertical distance).
3. Within each cluster, sort by x-position (for LTR) or by right edge (for RTL).
4. A "line" is a cluster of spans sharing a baseline.

Store using plain Python objects:

```python
@dataclass
class TextRun:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    origin: tuple[float, float]              # baseline origin
    font_name: str
    font_size: float
    color: int
    opacity: float
    seqno: int
    source: str  # "native" | "invisible-ocr"
    flags: list[str]

@dataclass
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]
    baseline_y: float
    direction: str  # "ltr" | "rtl" | "ttb"
    runs: list[TextRun]
    safety: str  # "safe" | "unsafe"
    unsafe_reasons: list[str]

@dataclass
class PageIndex:
    page_no: int
    width_pt: float
    height_pt: float
    rotation: int
    classification: str  # "native" | "scanned" | "hybrid" | "unknown"
    lines: list[TextLine]
    safe_line_count: int
    unsafe_line_count: int
```

---

## Safety Analysis

This is the most important component. A line is safe to replace ONLY if ALL of these pass:

### Check 1: Paint order — no later objects overlap

Use `page.get_bboxlog()` which returns entries like `(type_code, x0, y0, x1, y1)` in paint order.

Type codes from PyMuPDF:
- `"fill-text"`, `"stroke-text"`, `"ignore-text"` — text operations
- `"fill-path"`, `"stroke-path"` — vector graphics
- `"fill-image"` — images
- `"fill-shade"` — shadings

For each text run with seqno N, check if any non-text entry with seqno > N has a bbox that intersects the text run's bbox. If yes → **unsafe** (reason: "later object overlaps text").

```python
def check_paint_order_safety(run: TextRun, bboxlog: list) -> tuple[bool, str]:
    run_rect = fitz.Rect(run.bbox)
    for later_entry in bboxlog[run.seqno + 1:]:
        entry_type = later_entry[0]
        if entry_type in ("fill-text", "stroke-text", "ignore-text"):
            continue  # other text is fine
        entry_rect = fitz.Rect(later_entry[1:5])
        if run_rect.intersects(entry_rect):
            return False, f"later {entry_type} overlaps at seqno {bboxlog.index(later_entry)}"
    return True, ""
```

### Check 2: Visible text, not invisible OCR

From `get_texttrace()`, check the render mode. Invisible text (render mode 3, commonly used for OCR layers) should NOT be replaced. Mark as unsafe with reason "invisible OCR layer."

### Check 3: Unicode extraction is reliable

If `span["text"]` contains replacement characters (U+FFFD), private-use-area codepoints (U+E000–U+F8FF), or is empty despite having a non-zero bbox → **unsafe** (reason: "unreliable Unicode mapping").

### Check 4: Target font has glyph coverage

Before shaping, check that the target font covers the codepoints in the text. Use a fallback chain:

```
target_font → Noto Sans CJK SC → Noto Sans → Noto Sans Symbols → Noto Color Emoji
```

If ANY codepoint in a run has no coverage in the entire chain → **unsafe** (reason: "missing glyph coverage").

For v1: if the line contains mixed scripts requiring different fonts from the chain, still mark **safe** but track which segments need which font.

### Check 5: Replacement fits geometrically

After shaping the replacement text (see next section), compute:

```
scaleX = original_line_advance / shaped_target_advance
```

If `scaleX < 0.85` or `scaleX > 1.15` → **unsafe** (reason: "replacement text does not fit within original geometry").

Between 0.85–0.92 or 1.08–1.15: try adjusting font size by up to ±1pt. If it still doesn't fit → **unsafe**.

### Check 6: No problematic content

Mark unsafe if:
- Text is rotated (transform matrix has non-zero b or c components beyond a small epsilon)
- Text appears to be part of a form field or widget annotation
- Page has complex transparency groups involving text

---

## Font Metrics and Shaping

### Why a simple width ratio is wrong

`targetSize = originalSize × (originalWidth / targetWidth)` changes the text height, breaks baseline alignment, mishandles ligatures, and ignores kerning. Do NOT use this approach.

### Correct approach: shape-then-fit

For each safe line:

```python
import uharfbuzz as hb

def shape_line(text: str, font_path: str, font_size: float) -> ShapingResult:
    blob = hb.Blob.from_file_path(font_path)
    face = hb.Face(blob)
    font = hb.Font(face)
    font.scale = (int(font_size * 64), int(font_size * 64))

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)

    positions = buf.glyph_positions
    total_advance = sum(pos.x_advance for pos in positions) / 64.0

    return ShapingResult(
        advance=total_advance,
        glyph_count=len(positions),
        positions=positions,
    )
```

### Fitting algorithm

```python
def compute_fit(original_advance: float, original_height: float,
                target_font_path: str, text: str) -> FitResult:
    # Step 1: compute nominal font size from vertical fit
    face = load_face(target_font_path)
    upem = face.upem
    ascender = face.ascender   # positive
    descender = face.descender # negative
    nominal_size = original_height * upem / (ascender - descender)

    # Step 2: shape at nominal size
    shaped = shape_line(text, target_font_path, nominal_size)

    # Step 3: compute horizontal scale
    scale_x = original_advance / shaped.advance

    # Step 4: decide fitting strategy
    if 0.92 <= scale_x <= 1.08:
        return FitResult(font_size=nominal_size, scale_x=scale_x, method="scale")

    if 0.85 <= scale_x <= 1.15:
        # Try adjusting font size slightly
        adjusted_size = nominal_size * scale_x
        reshaped = shape_line(text, target_font_path, adjusted_size)
        new_scale = original_advance / reshaped.advance
        if 0.95 <= new_scale <= 1.05:
            return FitResult(font_size=adjusted_size, scale_x=new_scale, method="size_adjust")

    # Does not fit safely
    return FitResult(font_size=nominal_size, scale_x=scale_x, method="unsafe")
```

### CJK handling

**This is a v1 requirement**, not a later addition.

- CJK text has no word spaces; do NOT use word-spacing adjustment.
- Prefer x-scale within narrow bounds (0.95–1.05).
- Detect vertical writing mode from the text transform matrix or `dir: "ttb"`.
- Use Noto Sans/Serif CJK as fallback when the target font lacks CJK coverage.
- Segment lines by script/font-coverage so that Latin segments use the target font and CJK segments use the CJK fallback.

### Ligatures

Do NOT assume 1 codepoint = 1 glyph. PyMuPDF may report ligatures (fi, fl, ff, ffi, ffl) as multiple character entries where later components have glyph id -1 and zero-width bboxes. Always shape the full line/run as a single string through HarfBuzz — never sum individual character widths.

---

## Text Removal

Use PyMuPDF's redaction API to remove original text without damaging images or graphics:

```python
def remove_safe_text(page, safe_lines: list[TextLine]):
    # Snapshot existing links (redaction can remove overlapping links)
    original_links = list(page.get_links())

    for line in safe_lines:
        for run in line.runs:
            rect = fitz.Rect(run.bbox)
            # Slightly expand rect to ensure full glyph coverage
            rect = rect + (-0.5, -0.5, 0.5, 0.5)
            page.add_redact_annot(rect)

    # Apply redactions:
    # - Do NOT paint white fill over redacted areas
    # - Do NOT remove images
    # - Do NOT remove vector graphics
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_IMAGE_NONE,
    )

    # Restore any links that were removed
    current_links = list(page.get_links())
    for link in original_links:
        if link not in current_links:
            page.insert_link(link)
```

**Critical**: pass `images=fitz.PDF_REDACT_IMAGE_NONE` and `graphics=fitz.PDF_REDACT_IMAGE_NONE` to preserve non-text content. Do NOT use the redaction API's built-in text replacement feature — it only supports Base14 fonts and CJK, and doesn't give you the fitting control you need.

---

## Text Insertion

After redaction, insert replacement text at the original positions:

```python
def insert_replacement_text(page, safe_lines: list[TextLine],
                            font_path: str, fallback_cjk_path: str = None):
    # Embed the target font
    font_buffer = open(font_path, "rb").read()
    font_name = page.parent.add_font(fontname="TargetFont", fontbuffer=font_buffer)

    cjk_font_name = None
    if fallback_cjk_path:
        cjk_buffer = open(fallback_cjk_path, "rb").read()
        cjk_font_name = page.parent.add_font(fontname="CJKFallback", fontbuffer=cjk_buffer)

    for line in safe_lines:
        fit = line.fit_result  # computed during safety analysis

        # Segment by script if needed
        segments = segment_by_font_coverage(line.text, font_path, fallback_cjk_path)

        for segment in segments:
            chosen_font = font_name if segment.script != "cjk" else cjk_font_name
            if chosen_font is None:
                continue

            # Insert text at baseline position
            # Use page.insert_text() for single-line placement
            point = fitz.Point(segment.origin_x, segment.baseline_y)
            page.insert_text(
                point,
                segment.text,
                fontname=chosen_font,
                fontsize=fit.font_size,
                color=rgb_from_int(line.runs[0].color),
                overlay=True,
            )
```

**Note**: `insert_text` places text at a point using the baseline. The font must be embedded via `Document.add_font()` with the font file buffer. Check PyMuPDF docs for the exact API — the above is conceptual.

If `insert_text` doesn't support horizontal scaling, apply it via a text writer (`fitz.TextWriter`) which gives more control:

```python
writer = fitz.TextWriter(page.rect)
writer.append(point, segment.text, font=target_font_obj, fontsize=fit.font_size)
writer.write_text(page, morph=(point, fitz.Matrix(fit.scale_x, 1)))
```

---

## Audit Report

Produce two outputs alongside the PDF:

### 1. JSON report (`output_audit.json`)

```json
{
  "input_file": "input.pdf",
  "output_file": "output.pdf",
  "target_font": "Literata-Regular.ttf",
  "total_pages": 238,
  "pages_fully_converted": 214,
  "pages_partially_converted": 9,
  "pages_skipped": 15,
  "skipped_reasons": {
    "scanned_or_image_only": 6,
    "text_over_image": 4,
    "unreliable_unicode": 3,
    "watermark_or_overlay": 2
  },
  "per_page": [
    {
      "page": 1,
      "classification": "native",
      "total_lines": 42,
      "safe_lines": 42,
      "unsafe_lines": 0,
      "status": "fully_converted"
    },
    {
      "page": 15,
      "classification": "native",
      "total_lines": 38,
      "safe_lines": 30,
      "unsafe_lines": 8,
      "unsafe_reasons": ["later fill-image overlaps text (4 lines)", "scaleX out of bounds (4 lines)"],
      "status": "partially_converted"
    }
  ]
}
```

### 2. Human-readable summary (printed to stdout)

```
PDF Font Rewriter — Conversion Report
======================================
Input:  input.pdf (238 pages)
Output: output.pdf
Font:   Literata-Regular.ttf

Results:
  Fully converted:      214 pages (89.9%)
  Partially converted:    9 pages
  Skipped:               15 pages

Skip reasons:
  Scanned/image-only:    6 pages
  Text over image:        4 pages
  Unreliable Unicode:     3 pages
  Watermark/overlay:      2 pages

Pages with issues: 15, 23, 45, 67, 89, 102, 103, 105, 134, 156, 178, 189, 201, 220, 235
```

---

## CLI Interface

```
python refont.py INPUT.pdf --font ./fonts/Literata-Regular.ttf [OPTIONS]

Required:
  INPUT.pdf                    Input PDF file path
  --font PATH                  Target font file (.ttf or .otf)

Optional:
  --output PATH                Output PDF path (default: INPUT_refonted.pdf)
  --cjk-fallback PATH         CJK fallback font file (default: bundled Noto Sans CJK SC)
  --mode conservative|normal   Safety threshold (default: conservative)
  --report PATH                Audit report output path (default: alongside output PDF)
  --pages RANGE                Page range to process (e.g., "1-10,15,20-30")
  --preview                    Open a before/after comparison in the browser
  --dry-run                    Run safety analysis only, produce report, do not modify PDF
  --verbose                    Print per-page details during processing
```

Example usage:

```bash
# Basic usage
python refont.py book.pdf --font ./fonts/Literata-Regular.ttf

# Dry run to see what would be converted
python refont.py paper.pdf --font ./fonts/SourceSerif4-Regular.ttf --dry-run

# Process specific pages with CJK support
python refont.py mixed.pdf --font ./fonts/Literata-Regular.ttf \
  --cjk-fallback ./fonts/NotoSerifCJKsc-Regular.otf \
  --pages 1-50
```

---

## Project Structure

```
refont/
├── refont.py              # CLI entry point
├── classifier.py          # Page classification (native/scanned/hybrid)
├── extractor.py           # Text extraction + line grouping
├── safety.py              # Safety analysis (paint order, coverage, fit)
├── shaper.py              # HarfBuzz shaping + fit computation
├── remover.py             # Redaction-based text removal
├── inserter.py            # Target-font text insertion
├── report.py              # Audit report generation
├── models.py              # Data classes (TextRun, TextLine, PageIndex, FitResult)
├── font_utils.py          # Font loading, coverage checking, fallback chain
├── requirements.txt       # pymupdf, uharfbuzz, click
└── fonts/                 # Bundled fallback fonts (Noto Sans CJK, etc.)
    └── .gitkeep
```

---

## Key Implementation Warnings

1. **Do NOT paint white rectangles over text.** Use `apply_redactions()` with `fill=False` equivalent settings. White rectangles destroy any non-white background.

2. **Do NOT use the redaction API's built-in text replacement.** It only supports Base14 and CJK fonts. Insert text separately after redaction.

3. **Do NOT sum individual character widths.** Always shape the full run/line through HarfBuzz to account for kerning and ligatures.

4. **Do NOT treat spans as lines.** PDF spans are arbitrary fragments that may split mid-word or join multiple words. Group by baseline proximity.

5. **Do NOT process invisible text.** Invisible OCR layers (render mode 3) should be detected and skipped.

6. **Do NOT assume the target font covers all glyphs.** Always check coverage and fall back before insertion. Missing glyphs → tofu boxes → broken output.

7. **Snapshot links before redaction.** PyMuPDF's redaction can remove links whose rectangles overlap the redacted area. Save them and re-insert after.

8. **CJK is a v1 requirement.** The primary user reads Chinese text. Noto Sans/Serif CJK SC must be a bundled or configurable fallback from the start.

---

## Definition of Done (MVP)

The tool is done when:

- [ ] A native-text PDF (e.g., a LaTeX-generated paper) can be re-fonted end-to-end
- [ ] A Chinese-language native PDF can be re-fonted with CJK fallback
- [ ] Unsafe pages are left completely unchanged in the output
- [ ] Images, diagrams, and vector graphics on safe pages are untouched
- [ ] The audit report accurately reflects what was converted and why skips occurred
- [ ] `--dry-run` works and gives a useful preview of conversion coverage
- [ ] The output PDF opens correctly in Preview, Acrobat, and Zotero
- [ ] Processing a 300-page native PDF takes under 30 seconds

---

## What is explicitly OUT OF SCOPE for v1

- Scanned PDF / OCR support
- RTL text (Arabic, Hebrew) — detected and marked unsafe, left unchanged
- Vertical CJK writing mode — detected and marked unsafe, left unchanged
- Bold/italic style matching (if the original has bold, use the same style from a font family)
- Form field / annotation text replacement
- GUI / viewer application
- PDF/A compliance
- Batch processing of multiple files (trivially scriptable by the user)
