# Prompt: Mathematical Formulation of Visual Coherence for PDF Font Rewriting

You are helping formulate the **right mathematical problem** for a conservative PDF font-rewriting tool.

Do not assume our current framing is correct. In particular, do **not** assume the answer is simply “line-level vs paragraph-level fitting.” That is only how the failure currently appears in our implementation. The deeper problem is:

```text
When replacing the font of existing PDF text while preserving the original page geometry,
how do we decide which replacement is visually coherent, which is unacceptable,
and which text regions should be converted together or left alone?
```

We want you to be a first-principles mathematician/designer here. You may use lines, paragraphs, style clusters, text blocks, page-level rhythm, local neighborhoods, latent layout units, or another formulation if it is better.

## Tool Context

We already have a working lightweight implementation that:

- extracts native/searchable PDF text,
- preserves original baselines and page geometry,
- uses PyMuPDF `get_texttrace()` and `get_bboxlog()`,
- uses fontTools for target font visual metrics,
- uses HarfBuzz for shaped text advance/ink measurement,
- performs paint-order, Unicode, glyph-coverage, visibility, and geometry safety checks,
- redacts only accepted original text regions,
- inserts replacement text in the target font,
- leaves rejected content unchanged,
- writes an audit report.

This is not OCR software, not a viewer, not a full layout engine, not a raster reconstruction system, and not a large optimization pipeline.

The tool should remain:

- small,
- fast,
- conservative,
- dense/intelligent in architecture,
- geometry-preserving,
- explainable through audit data.

## Product Goal

The intended output is not “convert the maximum number of lines.”

The intended output is:

```text
A PDF that preserves the original document's geometry, rhythm, and trustworthiness,
while replacing text with the target font wherever the resulting visual system remains coherent.
```

Bad outcomes include:

- visibly stretched/compressed text,
- changed line rhythm,
- target text colliding with neighboring content,
- ghosting over scanned backgrounds,
- mixed target/original fonts inside what a reader perceives as one continuous text unit,
- converting a region just because each line narrowly passed a local threshold,
- skipping many lines just because a few local thresholds were too strict.

## Current Implementation Framing

Our current fitting unit is a visual line.

For each line, we compute:

```text
baseline_y
line bbox
non-space bbox
baseline-relative top/bottom envelope
original advance width
visible character count
role guess: body, heading, running header, page number, footnote, CJK body, mixed Latin/CJK, unknown
target visual metric: x-height, cap height, digit height, ideographic height, or actual shaped ink
target font size from role-relevant visual metric
target shaped advance via HarfBuzz
scale_x = original_advance / target_shaped_advance
vertical overflow
```

The current production rule is basically:

```text
If this line's scale_x and vertical envelope are inside strict bounds, convert it.
Otherwise leave it unchanged.
```

For Latin body text, the rough line-level acceptance band is:

```text
0.92 <= scale_x <= 1.08
```

This was intentionally conservative.

## Observed Failure

On a searchable scanned book page, a sans-serif target font produced a locally mixed result:

```text
some lines converted to target font
some lines stayed in the original font
```

This happened because individual lines exceeded the strict line-level scale band.

But when we ran a controlled relaxed experiment on one continuous paragraph, the result looked visually acceptable and coherent.

### Arial experiment

```text
converted lines in selected paragraph: 7
rejected lines in relaxed experiment: 0
median size: 9.931 pt
median scale_x: 1.062
max scale_x: 1.123
```

### Trebuchet experiment

```text
converted lines in selected paragraph: 7
rejected lines in relaxed experiment: 0
median size: 9.848 pt
median scale_x: 1.046
max scale_x: 1.112
```

Visually, Trebuchet looked especially coherent. Arial also looked acceptable, though it required stronger expansion.

This suggests our current mathematical decision policy is too local or too rigid. But again: do not assume the solution must be “paragraph-level fitting.” That is only one possible abstraction.

## Deeper Problem Statement

We need a mathematical framework that can distinguish:

### Case A: coherent adaptation

A region has moderate, consistent correction requirements:

```text
1.04, 1.06, 1.07, 1.08, 1.11
```

Some individual elements may exceed a strict local threshold, but the region as a whole may still preserve visual rhythm.

### Case B: local outlier distortion

Most elements fit, but one or two are outliers:

```text
1.02, 1.03, 1.04, 1.18
```

Maybe the outlier should be skipped, maybe the whole region should be skipped, maybe the region boundary is wrong.

### Case C: globally unsuitable target font

Everything requires a large correction:

```text
1.17, 1.19, 1.21, 1.23
```

Technically forceable does not mean visually honest.

### Case D: uncertain sparse evidence

Short lines, page numbers, headings, line endings, citations, footnotes, captions, hyphenated fragments, and indented starts do not have the same evidential value as full body lines.

The line:

```text
way of talking that uses language.
```

is short because it ends a paragraph. Its width is weak evidence about target font suitability.

### Case E: searchable-scan ghosting

In hybrid/searchable-scan PDFs, the page image can contain printed text underneath the native text layer. Even if paint order is safe, excessive size/scale mismatch can visually reveal ghosting or doubled text.

### Case F: mixed-font artifact

Partial conversion inside a reader-perceived continuous unit can be worse than no conversion. The policy must reason about visual coherence of the **set of converted/rejected elements**, not only each element independently.

## Available Data

For each extracted text element, we can cheaply obtain:

```text
text content
line/run bbox
baseline
character count
non-space bbox
source font size from PDF
target visual size estimate
target shaped advance
required horizontal scale_x
vertical envelope overflow
role guess and confidence
paint-order safety
glyph coverage
visibility / opacity / render mode
whether page is native or hybrid searchable-scan
neighboring line positions
page dimensions
```

We can also compute robust local/page statistics:

```text
median body line height
median baseline gap
median x-start
median line width
indentation patterns
scale_x distribution for candidate target font
role clusters
style clusters
```

Allowed lightweight math/tools:

- robust medians,
- MAD / robust dispersion,
- weighted scoring,
- local neighborhood consistency,
- style clustering from geometry,
- dynamic programming if simple and bounded,
- graph/interval grouping if simple,
- role-specific thresholds,
- optional tiny patch validation for hybrid pages.

Avoid:

- OCR,
- ML layout models,
- OpenCV,
- full-page raster optimization,
- deep layout reconstruction,
- slow global nonlinear optimization,
- turning this into a PDF viewer/layout engine.

## What We Want From You

Please formulate the best mathematical problem and solution.

You may reject our current “line vs paragraph” framing and replace it with a better one.

Please answer:

1. What is the correct unit of decision?

Examples, not prescriptions:

```text
line
run
paragraph
text block
style cluster
local baseline chain
connected component in layout space
page-level body rhythm cluster
```

If multiple units are needed, define their hierarchy and responsibilities.

2. What objective are we optimizing or satisfying?

For example, define a visual coherence / geometry preservation functional:

```text
cost(region, target_font, conversion_mask)
```

or a set of hard constraints plus soft penalties.

3. What are the hard constraints?

Examples:

```text
paint-order unsafe => cannot convert
missing glyph => cannot convert
invisible OCR => cannot convert
vertical collision => cannot convert
hybrid ghosting risk too high => cannot convert
```

4. What are the soft penalties?

Examples:

```text
horizontal scale distance from 1
scale dispersion inside a coherent region
vertical envelope overflow
role uncertainty
short-line unreliability
mixed-font discontinuity
hybrid page risk
font-size instability
anchor drift
```

5. How should the policy decide between:

```text
convert all candidates in a coherent region
convert a subset
skip the whole region
split the region differently
fall back to local line decisions
```

6. How should short/weak-evidence lines be weighted?

Examples:

```text
paragraph final line
heading
page number
caption
footnote
single citation line
hyphenated line
line with very few visible characters
```

7. How should hyphenated or full-measure body lines affect the decision?

They are often stronger evidence of the original text measure than short final lines.

8. How should the policy prevent mixed-font artifacts?

We need a mathematical condition for when partial conversion within a perceived region is worse than skipping the whole region.

9. How should native PDFs and hybrid searchable-scan PDFs differ?

In hybrid pages, the scanned background still contains original text pixels. Should the same visual-fit math apply with stricter thresholds, an extra ghosting penalty, or a separate feasibility rule?

10. What threshold families should exist for:

```text
conservative mode
normal mode
experimental/aggressive mode
native page
hybrid searchable-scan page
Latin body text
CJK body text
mixed Latin/CJK
headings/page numbers/footnotes/captions
```

11. How would your formulation classify the Arial and Trebuchet examples?

Given:

```text
Arial: median scale_x 1.062, max 1.123, visually acceptable but stronger expansion
Trebuchet: median scale_x 1.046, max 1.112, visually better
```

Would each pass? Under which mode? With what penalties?

12. Where should this sit in the existing pipeline?

Current simplified pipeline:

```text
extract text geometry
run non-visual hard safety checks
compute per-element visual fit candidates
decide accepted/rejected elements
redact accepted originals
insert replacement text
write audit
```

Should your method run:

```text
before line-level fit?
after per-element fit candidates?
as a page-level second pass?
as a region segmentation + selection problem?
```

13. Provide pseudocode.

The pseudocode should be compact enough to implement in Python without large new dependencies.

## Expected Answer Shape

Please provide:

- your formulation of the real problem,
- definitions of variables,
- hard constraints,
- soft objective or scoring function,
- grouping/segmentation method if needed,
- decision tree,
- thresholds or threshold families,
- pseudocode,
- worked examples using the Arial/Trebuchet data,
- edge cases and failure modes.

The ideal answer should be able to say both:

```text
This element fails a strict local threshold,
but the region-level system is coherent, so conversion is acceptable.
```

and:

```text
Partial conversion would create a worse mixed-font artifact,
so skip or split the region instead.
```

