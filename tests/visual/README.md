# Visual verification harness

Raster-based regression checks for the refont pipeline. Metrics are raster
proxies (ink masks at a fixed gray threshold), not typographic ground truth;
each report carries `provisional_notes` describing the approximations.

## Export mode (original vs refonted PDF)

```bash
.venv/bin/python -m refont OfSpirit.pdf --font "/System/Library/Fonts/Supplemental/Georgia.ttf" \
  --pages 1-12 --output /tmp/ofspirit_refonted.pdf --report /tmp/ofspirit_audit.json
.venv/bin/python -m refont.visual_verify compare OfSpirit.pdf /tmp/ofspirit_refonted.pdf \
  --pages 1-12 --out tests/visual/out/ofspirit --overlays
```

## Live mode (emulated compositor render of live page plans)

```bash
.venv/bin/python -m refont.visual_verify live OfSpirit.pdf \
  --font "/System/Library/Fonts/Supplemental/Georgia.ttf" \
  --pages 1-12 --out tests/visual/out/ofspirit-live --overlays
```

The live runner builds each page's plan with `build_live_page_plan`, erases
safe regions with white fill (mirroring the compositor's pixel erase) and
draws the runs with PyMuPDF, then compares against the original.

## What is measured

Per line (line regions come from the project's own extractor on the original):

- `changed` — did the rendered pixels in the line window change at all
- ink bbox before/after, top/bottom/left/right edge deltas (pt)
- `ink_height_ratio` — refonted ink height / original ink height
- `baseline_proxy_delta` — bottom of the densest ink band (provisional)
- flags: `ink_missing`, `ink_height`, `edge_left/right`, `baseline`,
  `overflow_top/bottom`, `clearance_above/below`

Per page:

- body ink-height ratio distribution (lines wider than 35% of the page)
- right-edge drift and baseline-delta distributions
- `rhythm_max_gap_delta_pt` — worst change in consecutive body baseline gaps
- `clearance_collisions` — adjacent ink bands whose vertical clearance
  dropped below 0.8pt (collision proxy)

Outputs: `report.json` plus optional `pageN_overlay.png` (red = flagged
line, orange = changed line without flags).

## Reading results

- Unchanged (skipped) lines should show `changed: false` and near-zero
  deltas; that is the harness's own sanity check.
- `body_ink_height_ratio` median should sit near 1.00; the p10/p90 spread is
  the perceived-size budget actually used.
- Any `ink_missing` or `clearance_collisions` is a hard failure to inspect.

- `xband_ratio` (page summary) — mean painted ink height of flat lowercase
  Latin glyphs (refonted/original). This is the primary perceived-size
  arbiter; `ink_height_ratio` measures the full ascender-to-descender span
  and also moves when the target font's vertical proportions differ from the
  source's, even at a perceptually correct size.
