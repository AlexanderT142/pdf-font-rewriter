# Live PDF Refonting Architecture Brief

## Why This Exists

This project currently rewrites PDF fonts as a finished-file operation. In Obsidian, the user clicks a rewrite button, waits several seconds, then sees a brief visual glitch as Obsidian opens the newly generated PDF or reloads the replaced PDF.

That glitch reveals the deeper product problem: the font change is not happening during reading. It happens once, after a batch conversion finishes. The target experience is much more ambitious:

> A PDF should feel as if it is already being rendered in the chosen font. As the user scrolls, visible and near-visible pages should appear smoothly in the target font, without a whole-file rewrite, tab switch, file replacement, or delayed PDF reopen.

This brief is not claiming that the ideas below are already the right architecture. These are methods that come to mind from the current codebase and PDF viewer constraints, but they are not fully thought through. There may be radically better, more intelligent approaches that avoid assumptions we are still trapped inside.

The goal of this document is to give another reasoning system enough project context to explore better architectures.

## Current Project Shape

Repository: `/Users/tianchenhao/projects/pdffont`

The project has two main parts:

1. A Python PDF font rewriting engine in `refont/`.
2. A desktop Obsidian plugin shell in `obsidian-plugin/`.

The current Python engine is conservative by design. It is not a general PDF editor, OCR tool, or universal renderer. It tries to replace only safe native text and leave unsafe content unchanged.

Core Python pipeline:

```text
Input PDF + target font
  -> classify each page
  -> extract native text lines/runs
  -> analyze safety
  -> redact safe original text
  -> insert replacement text using target font
  -> save output PDF
  -> write audit report
```

Important files:

- `pdf-font-rewriter-spec.md` describes the original build contract.
- `refont/converter.py` is the main rewrite loop.
- `refont/classifier.py` classifies pages.
- `refont/extractor.py` extracts text geometry.
- `refont/safety.py` decides what can be rewritten.
- `refont/remover.py` removes safe original text.
- `refont/inserter.py` inserts replacement text.
- `refont/shaper.py` and `refont/visual_fit.py` handle shaping and fit decisions.
- `obsidian-plugin/src/runner.ts` runs the helper binary and opens/reopens the resulting PDF.
- `obsidian-plugin/src/rewriteModal.ts` owns the current rewrite modal and button.
- `obsidian-plugin/README.md` explicitly says the plugin does not live-edit Obsidian's built-in PDF viewer page.

The current Obsidian flow:

```text
User opens PDF in Obsidian
  -> user clicks "Rewrite PDF font"
  -> plugin resolves target font and helper binary
  -> plugin spawns refont-helper
  -> helper writes a new PDF or temporary replacement PDF
  -> plugin waits for completion
  -> plugin opens the new PDF or reopens the current PDF
```

This makes the glitch structurally unavoidable. The viewer is not being transformed. A file is being produced after the fact.

## Current Technical Constraints

The existing system has useful strengths:

- It already has a safety model for which text should and should not be rewritten.
- It already uses PyMuPDF and HarfBuzz-oriented shaping/fitting logic.
- It already has font selection, helper installation, and Obsidian settings.
- It already supports page ranges, which suggests a possible path toward page-window processing.

But it also has important limits:

- It saves a rewritten PDF, so the browser/viewer only changes after output exists.
- Obsidian's built-in PDF viewer is not controlled by this plugin.
- A CSS-only approach cannot truly change PDF canvas-rendered text after PDF.js has rasterized it.
- Full-document conversion is too slow and disruptive for reading-time interaction.
- Replacing the vault PDF while a viewer is open causes reload-like behavior.
- Any live system must preserve links, annotations, search/copy behavior, and fallback behavior where possible.

## Smoothness Target

The desired experience is not merely "less delay." It is:

- No new PDF opening flash.
- No visible tab replacement.
- No whole-document wait before reading continues.
- Scrolling remains responsive.
- Current page renders quickly.
- Near-future pages are prepared before the user reaches them.
- Unsupported pages remain readable in the original rendering.
- Font switching feels like a display mode, not a destructive conversion.
- Exporting a rewritten PDF remains possible, but export is separate from reading.

An ideal mental model:

```text
Original PDF remains the source of truth.
Live Refont Mode changes how pages are rendered.
Export Refonted PDF is an optional later action.
```

## Ideas That Come To Mind, Not Yet Fully Thought Through

The following are not final recommendations. They are possible directions that need much sharper analysis.

### 1. Hide The Glitch Better

Keep the current batch rewrite architecture, but make the UI less jarring.

Possible tactics:

- Show a loading overlay.
- Disable `openAfterRewrite` by default.
- Keep the original PDF open and only show a notice when the output is ready.
- Open the output in a background leaf.

Why this is probably not enough:

- It does not solve the core issue.
- It still produces a separate completed PDF.
- It still cannot create real-time scroll behavior.

This is UX masking, not architectural progress.

### 2. Page-Window Batch Rewrite

Instead of rewriting the whole document, rewrite only the visible page plus nearby pages.

The plugin already has a visible-window concept in settings. A scroll-aware version could process page `N`, `N+1`, `N+2`, and maybe `N-1` as the user moves.

Possible architecture:

```text
Scroll position changes
  -> detect visible PDF sheet
  -> enqueue visible and nearby pages
  -> helper rewrites those pages into a small page-window PDF
  -> viewer switches to the rewritten page/window somehow
```

Open questions:

- How does Obsidian show page-level outputs without reopening files?
- Can a page-window PDF be visually stitched into the current viewer?
- Does this become a pile of temporary PDFs?
- Can scroll position be preserved perfectly?

This may reduce wait time, but it still thinks in generated PDFs.

### 3. Custom Obsidian PDF View With PDF.js

Create a new Obsidian view type for PDFs instead of using the built-in PDF viewer. The plugin would render PDFs itself using PDF.js, then control the scroll container, page virtualization, cache, overlays, and font substitution.

High-level flow:

```text
Open PDF in Live Refont View
  -> PDF.js loads original PDF bytes
  -> visible pages render immediately
  -> scroll observer tracks viewport
  -> near-visible pages are queued
  -> refont data or rendered page output is cached
  -> individual pages update in place
```

Possible strengths:

- No Obsidian built-in PDF reload.
- The plugin owns the page lifecycle.
- The plugin can prioritize visible pages.
- The plugin can maintain a cache keyed by PDF file hash, mtime, font, zoom, and mode.
- Export can remain separate.

Possible weaknesses:

- Rebuilding a serious PDF viewer is not small.
- Need search, copy, page navigation, links, annotations, zoom, selection, keyboard behavior.
- Obsidian mobile may be out of scope.
- PDF.js packaging inside Obsidian needs careful bundling.

This feels like the most plausible serious direction, but it may still be a stepping stone rather than the final architecture.

### 4. Page-Level Raster Cache

Use the existing Python engine to produce rewritten pages or page images on demand, then display them in the custom viewer.

Possible flow:

```text
PDF.js or helper renders original page immediately
  -> helper rewrites page N in background
  -> helper returns page N as a PDF page, PNG, or canvas-compatible image
  -> custom viewer swaps the visible page bitmap/layer
```

Why it might be smooth:

- Visible page can first show original content.
- Refonted page can fade in when ready.
- Nearby pages can be prefetched.
- The whole PDF is never reopened.

Why it may be intellectually unsatisfying:

- If we render rewritten pages as images, text selection/search may suffer.
- It avoids PDF.js text drawing rather than mastering it.
- It may create high memory use at zoom.
- It risks becoming "screenshots of PDFs" rather than a real PDF reading experience.

This may be the fastest prototype for perceived smoothness, but maybe not the smartest end-state.

### 5. Text Overlay Refont Layer

Let PDF.js render the original PDF page normally, then cover original text regions and draw replacement text in DOM/canvas overlays.

Possible flow:

```text
PDF.js renders original page canvas
  -> extractor identifies safe text line geometry
  -> overlay hides original safe text regions
  -> overlay draws replacement text using chosen font
```

Potential variants:

- DOM text spans positioned over the page.
- Canvas overlay per page.
- SVG overlay per page.
- Hybrid DOM for selectable text and canvas for visual fidelity.

Hard problems:

- Hiding original text without damaging images/backgrounds is hard.
- White rectangles only work on plain backgrounds.
- Original text is already baked into the canvas.
- Transparent overlays may show double text.
- Need accurate coordinate transforms under zoom, rotation, and scrolling.

This might work beautifully on simple white-background books and fail on complex pages. A smart system could classify when this is acceptable and fall back otherwise.

### 6. PDF.js Operator-List Substitution

Instead of rewriting a PDF file or covering rendered text, intercept the PDF.js page rendering pipeline.

PDF.js internally turns a page into an operator list, then renders those operations to canvas. A more radical approach would modify or wrap this rendering path:

```text
PDF.js parses page
  -> obtain page operator list
  -> identify text drawing operations
  -> suppress safe original text operations
  -> draw replacement text using target font
  -> leave all other operations unchanged
```

This seems closer to the ideal:

- No generated output file.
- No page image swap.
- No double text.
- No Obsidian PDF reload.
- Refonting becomes rendering-time behavior.

But it may be very hard:

- PDF.js internals are not designed as a stable font-substitution API.
- Mapping operator-list text back to the existing Python safety model may be nontrivial.
- Text rendering has complex transforms, encodings, embedded fonts, ligatures, CMaps, vertical text, and fallback behavior.
- Need to preserve selection/search/text layer behavior.
- PDF.js upgrades could break private hooks.

This may be the most elegant direction if it can be made stable, but it needs serious investigation.

### 7. Browser-Side Reimplementation Of The Safety/Fit Engine

Port enough of the Python safety/fitting pipeline to TypeScript/WebAssembly so the custom viewer does not need to spawn a Python helper for every page.

Possible components:

- PDF.js for parsing/rendering.
- HarfBuzz WASM for shaping.
- OpenType/fontTools-equivalent JS libraries for glyph coverage and metrics.
- Browser workers for page analysis.
- IndexedDB or local file cache for results.

Why it could be powerful:

- Lower process overhead.
- Easier scroll-driven scheduling.
- Cross-platform viewer logic.
- Potentially no helper binary for live viewing.

Why it could be costly:

- It duplicates logic that already exists in Python.
- PDF safety analysis may be worse if PDF.js does not expose the same paint-order and low-level geometry data we rely on.
- A partial port could drift from export behavior.

Maybe the right split is: browser-side preview for speed, Python-side export for final document production.

### 8. Hybrid: Live Preview Engine Plus Export Engine

Separate the product into two engines:

```text
Live Refont View
  -> optimized for smooth reading
  -> may use approximations and fallbacks
  -> page-local, cache-heavy, scroll-driven

Export Refonted PDF
  -> optimized for durable output PDF
  -> uses current conservative PyMuPDF pipeline
  -> full audit report
```

This may be the most honest product model. Reading-time smoothness and durable PDF rewriting are related but not identical. Trying to force one engine to serve both may be causing architectural confusion.

The risk is consistency: users may see one thing in Live View and get a slightly different result in exported PDF.

## Questions For Deeper Exploration

Please challenge the assumptions in this brief. Some specific questions:

1. Is there a way to make font substitution happen inside PDF.js rendering without depending on unstable private internals?
2. Can PDF.js text-layer data plus operator-list data reconstruct enough geometry for safe live refonting?
3. Can the existing PyMuPDF safety model produce a compact per-page "refont plan" instead of a rewritten PDF?
4. What should the refont plan contain?
5. Could a helper stream page-level plans or page-level renders over stdio/WebSocket instead of writing PDFs?
6. What caching strategy would make scrolling feel instant after the first pass?
7. How should cancellation work when the user scrolls quickly?
8. What is the right fallback when a page is too complex?
9. Is it smarter to preserve selectable text, or is first-class visual comfort more important for v1?
10. Can original page rendering and refonted text rendering be composited without visible double text?
11. Is there a third architecture beyond file rewrite and viewer rewrite?
12. What would the best architecture look like if we ignored the current implementation completely?

## A Possible Refined Target Architecture

This is only a sketch:

```text
Obsidian Live Refont View
  -> owns PDF scroll container
  -> uses PDF.js for baseline PDF loading/rendering
  -> virtualizes pages
  -> observes viewport
  -> asks Refont Planner for visible page plans
  -> renders original immediately
  -> applies refonted rendering when page plan is ready
  -> prefetches nearby pages
  -> caches page plans and rendered outputs
  -> exposes Export Refonted PDF separately
```

Potential helper interface:

```text
refont-helper live-plan input.pdf \
  --font target.ttf \
  --page 37 \
  --mode conservative \
  --json
```

Potential response:

```json
{
  "page": 37,
  "classification": "native",
  "safeLines": [
    {
      "text": "Example text",
      "bbox": [72.0, 120.5, 420.0, 135.2],
      "baseline": [72.0, 132.0],
      "fontSize": 11.4,
      "scaleX": 0.98,
      "color": "#111111",
      "segments": [
        {
          "text": "Example text",
          "font": "target",
          "xOffset": 0
        }
      ]
    }
  ],
  "unsafeLines": [
    {
      "bbox": [72.0, 500.0, 430.0, 515.0],
      "reason": "later object overlaps text"
    }
  ]
}
```

But this plan format may be too naive. A better system may need:

- exact transforms, not just bboxes;
- paint-order metadata;
- clipping paths;
- text rendering mode;
- opacity;
- original font metrics;
- per-glyph placement;
- replacement glyph IDs and advances;
- page rotation and viewport transform;
- background reconstruction instructions.

## What Would Count As Success

A successful architecture should make this feel true:

> I open a PDF, turn on my preferred reading font, and scroll. Pages appear in that font as part of the reading experience. I never feel that a separate PDF is being generated behind my back.

Technical success criteria:

- No file-open flash after enabling live mode.
- Visible page is never blocked by whole-document conversion.
- Fast scrolling remains responsive.
- Page processing is cancellable and prioritized.
- Original rendering is always available as fallback.
- Refonted pages are cached.
- Export remains available but is not required for reading.
- The system is honest about pages it cannot safely refont.

## Final Request To The Reviewing System

Do not treat the options above as the option set. They are just the obvious methods that surfaced from the current codebase.

Please look for a more intelligent architecture. In particular, look for a way to make refonting a rendering-time phenomenon rather than a document-rewrite phenomenon, while still preserving enough safety, fidelity, and reading ergonomics to be useful inside Obsidian.
