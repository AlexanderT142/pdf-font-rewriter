"""Real glyph-ink measurement from a rasterized page.

PyMuPDF texttrace/rawdict char bboxes are font boxes — every char on a line
reports height == font size — so the perceptual char statistics in
``visual_fit`` cannot be measured from them. Embedded font programs are
frequently bare CID-keyed CFF subsets without a codepoint-to-glyph mapping,
so parsing the source font is not generally possible either.

This sampler measures what is actually painted: one grayscale raster per
page, with per-char ink extents scanned inside each char's own font-box
columns. The font box bounds the scan vertically, which keeps neighboring
lines out of the measurement.

Limitations (all self-protecting via the plausibility windows in
``visual_fit._original_metric``, which reject implausible values):

- light/colored text near the gray threshold measures approximately
- text over images or shaded backgrounds measures the background too
- kerned/italic neighbors can bleed into a char's columns (medians absorb it)
- rotated pages are not sampled at all
"""

from __future__ import annotations

import fitz

from .models import CharGeometry, RectTuple

# 128 approximates the 50%-coverage contour of antialiased glyph edges; a
# laxer threshold (e.g. 200) counts faint edge pixels and inflates measured
# ink heights by roughly a pixel per edge.
INK_THRESHOLD = 128
_INK_TABLE = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))
DEFAULT_ZOOM = 3.0


class PageInkSampler:
    def __init__(self, page: fitz.Page, zoom: float = DEFAULT_ZOOM) -> None:
        self.enabled = int(page.rotation) == 0
        self.zoom = zoom
        if not self.enabled:
            self.width = 0
            self.height = 0
            self.stride = 0
            self.mask = b""
            return
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
        self.width = pix.width
        self.height = pix.height
        self.stride = pix.stride
        self.mask = pix.samples.translate(_INK_TABLE)

    def char_ink_height_pt(self, char: CharGeometry) -> float | None:
        """Ink height of one glyph in pt, or None if nothing is painted."""
        extent = self._ink_rows(char.bbox)
        if extent is None:
            return None
        top, bottom = extent
        return (bottom - top + 1) / self.zoom

    def line_ink_extent_pt(self, bbox: RectTuple) -> tuple[float, float] | None:
        """(ink_top_y, ink_bottom_y) in page pt within a line's font box."""
        extent = self._ink_rows(bbox, pad_pt=1.0)
        if extent is None:
            return None
        top, bottom = extent
        return (top / self.zoom, (bottom + 1) / self.zoom)

    def _ink_rows(self, bbox: RectTuple, pad_pt: float = 0.0) -> tuple[int, int] | None:
        if not self.enabled:
            return None
        z = self.zoom
        x0 = max(0, min(self.width, int(bbox[0] * z)))
        x1 = max(0, min(self.width, int(bbox[2] * z) + 1))
        y0 = max(0, min(self.height, int((bbox[1] - pad_pt) * z)))
        y1 = max(0, min(self.height, int((bbox[3] + pad_pt) * z) + 1))
        if x1 <= x0 or y1 <= y0:
            return None
        first = None
        last = None
        for row in range(y0, y1):
            start = row * self.stride
            if self.mask[start + x0 : start + x1].count(1) > 0:
                if first is None:
                    first = row
                last = row
        if first is None or last is None:
            return None
        return (first, last)
