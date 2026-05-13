# Prompt: PDF Font Rewriter Visual Geometry Architecture Review

You are reviewing a Python PDF font-rewriting tool. Treat this as a serious architecture/design task, not a generic brainstorming task.

## Product Philosophy

This tool should be **small, dense, intelligent, conservative, and fast**.

It is not a PDF viewer, not OCR software, not a universal PDF transformer, and not a giant slow raster-processing pipeline. The goal is to use the structure already present inside native/searchable PDFs, make precise decisions with PDF geometry and font metrics, and rewrite only what can be rewritten safely.

The guiding principles:

- Trust over coverage.
- Per-line decisions over page-level guesses.
- Preserve original PDF geometry.
- Preserve images, diagrams, scanned backgrounds, links, and vector content.
- Avoid OCR, OpenCV, Tesseract, or full-page raster reconstruction.
- Prefer high-signal PDF internals: texttrace, bboxlog paint order, font metrics, HarfBuzz shaping.
- Produce an audit trail explaining what changed and what was skipped.
- Keep the implementation architecturally lean: no big framework, no heavyweight visual diff loop as the main algorithm, no slow global optimization unless strictly necessary.

## Current Tool

Repo structure:

```text
refont/
  refont.py        CLI
  converter.py     pipeline
  classifier.py    page classification
  extractor.py     text extraction and visual line grouping
  safety.py        per-line safety analysis
  shaper.py        HarfBuzz shaping and geometric fit
  remover.py       redaction-based original text removal
  inserter.py      replacement text insertion
  report.py        JSON/stdout audit report
  font_utils.py    font loading, cmap coverage, CJK fallback
  models.py        dataclasses
```

Stack:

- Python 3.11+
- PyMuPDF / fitz
- uharfbuzz
- fontTools
- argparse CLI

Forbidden / out of scope:

- OCR
- image-processing-based text recognition
- rasterizing pages and rebuilding them
- GUI
- arbitrary malformed PDF support
- RTL and vertical writing in v1, except detect and skip

## Current Pipeline

Input:

```text
input.pdf + target font file
```

Pipeline:

1. Open PDF with PyMuPDF.
2. Classify each page:
   - `native`: has native text, no full-page image.
   - `scanned`: full-page image, no native text.
   - `hybrid`: full-page image plus native text layer.
   - `unknown`.
3. Extract text only from `native` and `hybrid`.
4. Group text into visual lines.
5. Run per-line safety checks.
6. Redact original safe text only.
7. Insert replacement text using target font and fallback fonts.
8. Save output PDF and JSON audit report.

Important recent fix:

Originally, `hybrid` pages were skipped unconditionally. That was wrong for common searchable-scan PDFs, where a scanned page image is painted first and a clean visible native text layer is painted on top. The tool now lets `hybrid` pages flow through extraction and safety analysis. Paint order decides whether text is safe.

## Current Extraction Method

Preferred extraction:

```python
page.get_texttrace()
```

Why:

- exposes low-level span data
- includes `seqno`
- includes opacity/type/render information
- includes character origins and bboxes
- can be connected to `page.get_bboxlog()` paint order

Important detail:

`get_texttrace()` spans can contain multiple visual lines. The extractor now splits trace chars by baseline before creating runs. Without this, a whole paragraph can be treated as one huge line, causing nonsensical fit ratios such as `scaleX=0.007`.

Fallback extraction:

```python
page.get_text("rawdict")
```

Grouping:

- sort runs by seqno / position
- cluster by baseline proximity
- sort LTR lines by x-position
- create `TextLine` objects with text, bbox, baseline, direction, runs

## Current Safety Method

For each `TextLine`, mark safe only if all checks pass.

Checks:

1. Direction:
   - LTR only for v1.
   - RTL, vertical, rotated, unknown direction are unsafe.

2. Text visibility:
   - invisible OCR layers are unsafe.
   - opacity <= 0 is unsafe.

3. Unicode reliability:
   - U+FFFD unsafe.
   - private-use codepoints unsafe.
   - empty text with non-zero bbox unsafe.

4. Glyph coverage:
   - target font first.
   - CJK fallback if configured or discoverable.
   - segment mixed text by font coverage.
   - if any codepoint lacks coverage, unsafe.

5. Paint order:
   - use `page.get_bboxlog()`.
   - non-text objects painted after text and overlapping the run bbox make the run unsafe.
   - text over a background image is allowed if the image is painted before the text.

6. Geometry fit:
   - shape full line/segments with HarfBuzz.
   - compute target advance.
   - compare against original line advance.
   - allow only conservative horizontal scale.

7. Problematic content:
   - widget/form areas unsafe.
   - complex unsupported text geometry unsafe.

## Current Removal and Insertion

Removal:

- uses PyMuPDF redaction annotations.
- only redacts safe text run bboxes.
- expands redaction boxes slightly.
- applies redactions while preserving images and vector graphics.
- snapshots/restores links because redaction can remove link annotations.

Insertion:

- registers/embeds target font and fallback fonts.
- inserts text back at original baseline.
- segments mixed-font lines.
- uses mild horizontal scaling where supported.

## Current Visual-Fit Problem

The current size computation is structurally correct but visually naive.

Current idea in `shaper.py`:

```text
nominal_size = original_line_height * target_upem / (target_ascender - target_descender)
shape text at nominal_size
scale_x = original_advance / target_advance
accept/reject based on scale_x
```

Problem:

Two fonts with the same point size can look visually different. The em box is metadata, not perceived size.

Visual size depends on:

- x-height
- cap height
- ascenders
- descenders
- actual glyph ink bounds
- internal leading
- stroke weight
- optical size
- CJK ideographic box
- punctuation and whitespace rhythm
- line type: heading, body, footnote, page number, running header

Result:

Even if metadata size and width fit are acceptable, replacement text can look too large/small, change perceived line spacing, collide with scanned background text, or feel visually wrong.

## Desired Improvement

Design an elegant **visual geometry fit layer**.

The goal is:

```text
Keep the original PDF geometry and reading rhythm,
but replace the font in a way that looks visually equivalent in size.
```

Not:

```text
Use the same point size.
```

Not:

```text
Globally scale the whole document by trial and error.
```

Not:

```text
Rasterize everything and optimize against pixels.
```

## Design Direction We Are Considering

Introduce a `VisualFitProfile` or similar module.

Possible responsibilities:

1. Determine line role:
   - body
   - heading
   - running header
   - page number
   - footnote
   - caption
   - CJK body
   - mixed Latin/CJK

2. Determine original visual target:
   - line bbox height
   - original baseline
   - neighboring line baselines
   - median body-line height on page
   - original font size if trustworthy
   - original glyph ink bounds if obtainable

3. Determine target-font visual metrics:
   - x-height
   - cap height
   - ascender/descender
   - actual shaped glyph ink bbox for representative text
   - CJK ideographic visual box

4. Choose font size by visual metric:
   - lowercase-heavy body lines: match x-height
   - all-caps/title lines: match cap height
   - numeric/page-number lines: match digit height
   - CJK lines: match ideographic box
   - mixed lines: choose shared baseline and segment-specific font metrics without breaking line rhythm

5. Then shape and horizontally fit:
   - HarfBuzz shape full line/segments.
   - compute advance.
   - allow mild x-scale.
   - reject if scale is ugly or geometry is unsafe.

6. Preserve vertical rhythm:
   - avoid changing baseline positions.
   - do not let target glyph ink exceed original line box by too much.
   - avoid collisions with adjacent lines.
   - apply page-level smoothing so body text size is stable across a paragraph/page.

7. Remain conservative:
   - if visual fit is ambiguous, skip the line.
   - if a replacement would look like a second layer over scanned text rather than a clean replacement, flag it.

## Hard Architectural Constraint

Do not propose a huge slow tool.

We want a compact architecture with high leverage:

- fontTools for font metrics
- HarfBuzz for shaping
- PyMuPDF for PDF geometry and insertion
- maybe optional targeted micro-render checks for validation, not as the core algorithm

Acceptable:

- per-font cached metric profiles
- per-page body-style inference
- per-line visual fit classification
- optional tiny glyph/sample render for calibration if cheap and well-contained

Avoid:

- full-page iterative raster optimization
- OCR
- OpenCV
- ML layout model
- browser-based rendering dependency
- slow multi-pass global optimizer
- rewriting the PDF as images

## What I Want From You

Please return a concrete architecture proposal.

Include:

1. A critique of the current method.
2. A precise definition of “visual geometry consistency” for this tool.
3. A proposed module design, including dataclasses/functions.
4. The exact font metrics to extract with fontTools.
5. The exact shaping/measurement steps to run with HarfBuzz.
6. How to handle Latin body text, headings, footnotes, page numbers, CJK, and mixed Latin/CJK.
7. How to preserve vertical rhythm across paragraphs/pages.
8. How to choose font size and horizontal scale.
9. Conservative rejection rules.
10. Performance strategy for a 300-page PDF.
11. Testing strategy using:
    - native generated PDF
    - searchable scanned PDF with background image + visible text layer
    - CJK native PDF
    - mixed Latin/CJK PDF
12. A step-by-step implementation plan that fits the existing repo.

Please be specific. I do not want generic statements like “use visual metrics” or “compare font sizes.” Give concrete formulas, thresholds, fallback behavior, caching strategy, and where the code should live.

Also identify any traps:

- PyMuPDF insertion limitations
- font bbox vs ink bbox mismatch
- PDF text layer over scanned image complications
- glyph coverage / fallback segmentation issues
- CJK metric pitfalls
- line grouping edge cases
- when not to convert even though text is technically present

