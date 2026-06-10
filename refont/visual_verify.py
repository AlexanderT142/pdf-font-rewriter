"""Raster-based visual verification harness.

Compares an original PDF against either a refonted PDF (export mode) or an
emulated render of a live page plan, using the project's own text-line
extraction on the ORIGINAL document to define line regions.

All metrics here are raster proxies, not typographic ground truth:

- Ink masks come from a fixed grayscale threshold, so colored/low-contrast
  text and non-white backgrounds are measured approximately (provisional).
- The baseline proxy is the bottom of the densest ink band per line; it can
  drift on lines dominated by descenders or underlines (provisional).
- Live emulation paints the safe-region erase as a white rectangle, like the
  compositor's pixel erase; on non-white backgrounds this overstates erase
  damage (provisional).

Usage:
  python -m refont.visual_verify compare ORIG.pdf REFONTED.pdf --out DIR [--pages 1-10] [--zoom 4] [--overlays]
  python -m refont.visual_verify live ORIG.pdf --font FONT.ttf --out DIR [--pages 3] [--mode conservative] [--overlays]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import fitz

from .classifier import classify_page
from .extractor import extract_page_index
from .ink_sampler import PageInkSampler
from .models import TextLine

INK_THRESHOLD = 200  # gray < threshold counts as ink (provisional for light text)
_INK_TABLE = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))

# Flag thresholds, in PDF points unless noted.
FLAG_INK_HEIGHT_RATIO = 0.06
FLAG_EDGE_PT = 1.5
FLAG_BASELINE_PT = 0.8
FLAG_OVERFLOW_PT = 1.0
FLAG_CLEARANCE_PT = 0.8  # adjacent ink bands closer than this are collision risks
CHANGED_MIN_DIFF_PX = 15

PROVISIONAL_NOTES = [
    "ink mask uses a fixed grayscale threshold; light/colored text is approximate",
    "baseline proxy = bottom of densest ink band; provisional on descender-heavy lines",
    "live emulation erases safe regions with white fill, like the compositor pixel erase",
    "line windows are clamped at midpoints to vertical neighbors; extreme overflow shows up in gap-band metrics instead",
]


@dataclass
class LineMetrics:
    index: int
    text_preview: str
    bbox: tuple[float, float, float, float]
    changed: bool
    diff_px: int
    orig_ink: tuple[float, float, float, float] | None
    new_ink: tuple[float, float, float, float] | None
    top_delta: float | None = None
    bottom_delta: float | None = None
    left_delta: float | None = None
    right_delta: float | None = None
    ink_height_ratio: float | None = None
    baseline_proxy_delta: float | None = None
    flags: list[str] = field(default_factory=list)


class PageRaster:
    def __init__(self, page: fitz.Page, zoom: float) -> None:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
        self.zoom = zoom
        self.width = pix.width
        self.height = pix.height
        self.stride = pix.stride
        self.mask = pix.samples.translate(_INK_TABLE)

    def row(self, row: int, x0: int, x1: int) -> bytes:
        start = row * self.stride
        return self.mask[start + x0 : start + x1]

    def window_rows(self, window: tuple[int, int, int, int]) -> list[bytes]:
        x0, y0, x1, y1 = window
        return [self.row(row, x0, x1) for row in range(y0, y1)]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _window_px(
    raster: PageRaster,
    bbox_pt: tuple[float, float, float, float],
    pad_x_pt: float,
    pad_top_pt: float,
    pad_bottom_pt: float,
) -> tuple[int, int, int, int]:
    z = raster.zoom
    x0 = _clamp(int((bbox_pt[0] - pad_x_pt) * z), 0, raster.width)
    x1 = _clamp(int((bbox_pt[2] + pad_x_pt) * z) + 1, 0, raster.width)
    y0 = _clamp(int((bbox_pt[1] - pad_top_pt) * z), 0, raster.height)
    y1 = _clamp(int((bbox_pt[3] + pad_bottom_pt) * z) + 1, 0, raster.height)
    return (x0, y0, x1, y1)


def _ink_bbox_pt(rows: list[bytes], window: tuple[int, int, int, int], zoom: float) -> tuple[float, float, float, float] | None:
    x0w, y0w, _, _ = window
    ink_rows = [index for index, row in enumerate(rows) if row.count(1) > 0]
    if not ink_rows:
        return None
    y0 = ink_rows[0]
    y1 = ink_rows[-1]
    x_min = None
    x_max = None
    for index in ink_rows:
        row = rows[index]
        first = row.find(1)
        last = row.rfind(1)
        if first >= 0:
            x_min = first if x_min is None else min(x_min, first)
            x_max = last if x_max is None else max(x_max, last)
    if x_min is None:
        return None
    return (
        (x0w + x_min) / zoom,
        (y0w + y0) / zoom,
        (x0w + x_max + 1) / zoom,
        (y0w + y1 + 1) / zoom,
    )


def _baseline_proxy_pt(rows: list[bytes], window: tuple[int, int, int, int], zoom: float) -> float | None:
    counts = [row.count(1) for row in rows]
    if not counts:
        return None
    peak = max(counts)
    if peak < 4:
        return None
    peak_index = counts.index(peak)
    row = peak_index
    while row + 1 < len(counts) and counts[row + 1] >= 0.30 * peak:
        row += 1
    return (window[1] + row + 1) / zoom


def _diff_px(rows_a: list[bytes], rows_b: list[bytes]) -> int:
    total = 0
    for row_a, row_b in zip(rows_a, rows_b):
        if row_a == row_b:
            continue
        total += (int.from_bytes(row_a, "big") ^ int.from_bytes(row_b, "big")).bit_count()
    return total


def _extract_lines(page: fitz.Page, page_no: int) -> list[TextLine]:
    classification = classify_page(page)
    page_index = extract_page_index(page, page_no, classification)
    return [line for line in page_index.lines if line.text.strip()]


_XBAND_CHARS = set("acemnorsuvwxz")


def _page_xband_mean_pt(page: fitz.Page, page_no: int, zoom: float) -> float | None:
    """Mean painted ink height of flat-ish lowercase Latin glyphs on body-width
    lines, using the page's own text extraction. This tracks perceived text
    size more directly than the full-span ink_height_ratio, which conflates
    size with ascender/descender proportions (provisional: Latin-only, mixes
    converted and unconverted lines)."""
    sampler = PageInkSampler(page, zoom=zoom)
    if not sampler.enabled:
        return None
    heights: list[float] = []
    for line in _extract_lines(page, page_no):
        if (line.bbox[2] - line.bbox[0]) < 0.35 * float(page.rect.width):
            continue
        for run in line.runs:
            for char in run.chars:
                if char.char in _XBAND_CHARS:
                    height = sampler.char_ink_height_pt(char)
                    if height:
                        heights.append(height)
    if len(heights) < 20:
        return None
    return sum(heights) / len(heights)


def _vertical_neighbors(lines: list[TextLine]) -> tuple[dict[int, int], dict[int, int]]:
    """For each line index, the closest line above/below with x-overlap."""
    above: dict[int, int] = {}
    below: dict[int, int] = {}
    for i, line in enumerate(lines):
        best_above = None
        best_below = None
        for j, other in enumerate(lines):
            if i == j:
                continue
            x_overlap = min(line.bbox[2], other.bbox[2]) - max(line.bbox[0], other.bbox[0])
            min_width = max(1.0, min(line.bbox[2] - line.bbox[0], other.bbox[2] - other.bbox[0]))
            if x_overlap < 0.2 * min_width:
                continue
            if other.bbox[3] <= line.bbox[1] + 0.5:
                if best_above is None or other.bbox[3] > lines[best_above].bbox[3]:
                    best_above = j
            elif other.bbox[1] >= line.bbox[3] - 0.5:
                if best_below is None or other.bbox[1] < lines[best_below].bbox[1]:
                    best_below = j
        if best_above is not None:
            above[i] = best_above
        if best_below is not None:
            below[i] = best_below
    return above, below


def _line_windows(
    lines: list[TextLine],
    raster: PageRaster,
) -> list[tuple[int, int, int, int]]:
    above, below = _vertical_neighbors(lines)
    windows: list[tuple[int, int, int, int]] = []
    for i, line in enumerate(lines):
        height = max(1.0, line.bbox[3] - line.bbox[1])
        pad_top = 0.35 * height + 1.0
        pad_bottom = 0.35 * height + 1.0
        if i in above:
            gap = line.bbox[1] - lines[above[i]].bbox[3]
            if gap > 0:
                pad_top = min(pad_top, gap / 2)
        if i in below:
            gap = lines[below[i]].bbox[1] - line.bbox[3]
            if gap > 0:
                pad_bottom = min(pad_bottom, gap / 2)
        windows.append(_window_px(raster, line.bbox, 1.5, pad_top, pad_bottom))
    return windows


def _measure_lines(
    lines: list[TextLine],
    raster_orig: PageRaster,
    raster_new: PageRaster,
    zoom: float,
) -> list[LineMetrics]:
    windows = _line_windows(lines, raster_orig)
    records: list[LineMetrics] = []
    for index, (line, window) in enumerate(zip(lines, windows)):
        rows_orig = raster_orig.window_rows(window)
        rows_new = raster_new.window_rows(window)
        diff = _diff_px(rows_orig, rows_new)
        area = max(1, (window[2] - window[0]) * (window[3] - window[1]))
        changed = diff > max(CHANGED_MIN_DIFF_PX, int(0.0015 * area))
        orig_ink = _ink_bbox_pt(rows_orig, window, zoom)
        new_ink = _ink_bbox_pt(rows_new, window, zoom)
        record = LineMetrics(
            index=index,
            text_preview=line.text.strip()[:48],
            bbox=tuple(round(v, 2) for v in line.bbox),
            changed=changed,
            diff_px=diff,
            orig_ink=orig_ink,
            new_ink=new_ink,
        )
        if changed and orig_ink and new_ink is None:
            record.flags.append("ink_missing")
        if orig_ink and new_ink:
            record.top_delta = new_ink[1] - orig_ink[1]
            record.bottom_delta = new_ink[3] - orig_ink[3]
            record.left_delta = new_ink[0] - orig_ink[0]
            record.right_delta = new_ink[2] - orig_ink[2]
            orig_height = orig_ink[3] - orig_ink[1]
            new_height = new_ink[3] - new_ink[1]
            if orig_height > 0.5:
                record.ink_height_ratio = new_height / orig_height
            baseline_orig = _baseline_proxy_pt(rows_orig, window, zoom)
            baseline_new = _baseline_proxy_pt(rows_new, window, zoom)
            if baseline_orig is not None and baseline_new is not None:
                record.baseline_proxy_delta = baseline_new - baseline_orig
            if changed:
                if record.ink_height_ratio is not None and abs(record.ink_height_ratio - 1.0) > FLAG_INK_HEIGHT_RATIO:
                    record.flags.append("ink_height")
                if abs(record.left_delta) > FLAG_EDGE_PT:
                    record.flags.append("edge_left")
                if abs(record.right_delta) > FLAG_EDGE_PT:
                    record.flags.append("edge_right")
                if record.baseline_proxy_delta is not None and abs(record.baseline_proxy_delta) > FLAG_BASELINE_PT:
                    record.flags.append("baseline")
                if record.top_delta < -FLAG_OVERFLOW_PT:
                    record.flags.append("overflow_top")
                if record.bottom_delta > FLAG_OVERFLOW_PT:
                    record.flags.append("overflow_bottom")
        records.append(record)
    return records


def _gap_band_metrics(
    lines: list[TextLine],
    records: list[LineMetrics],
    raster_orig: PageRaster,
    raster_new: PageRaster,
    zoom: float,
) -> list[dict[str, Any]]:
    """Vertical clearance loss between adjacent ink bands (collision proxy).

    Measurement windows are clamped at the midpoint between neighbors, so two
    bands touching at the midpoint read as clearance 0 — a definite collision.
    """
    _, below = _vertical_neighbors(lines)
    results: list[dict[str, Any]] = []
    for i, j in below.items():
        rec_a, rec_b = records[i], records[j]
        if not rec_a.orig_ink or not rec_b.orig_ink or not rec_a.new_ink or not rec_b.new_ink:
            continue
        if not (rec_a.changed or rec_b.changed):
            continue
        orig_clearance = rec_b.orig_ink[1] - rec_a.orig_ink[3]
        new_clearance = rec_b.new_ink[1] - rec_a.new_ink[3]
        if new_clearance < FLAG_CLEARANCE_PT and new_clearance < orig_clearance - 0.3:
            results.append(
                {
                    "above_line": i,
                    "below_line": j,
                    "orig_clearance_pt": round(orig_clearance, 2),
                    "new_clearance_pt": round(new_clearance, 2),
                }
            )
            records[i].flags.append("clearance_below")
            records[j].flags.append("clearance_above")
    return results


def _distribution(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def pick(quantile: float) -> float:
        position = _clamp(int(quantile * (len(ordered) - 1) + 0.5), 0, len(ordered) - 1)
        return ordered[position]

    return {
        "n": len(ordered),
        "median": round(float(median(ordered)), 4),
        "p10": round(pick(0.10), 4),
        "p90": round(pick(0.90), 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
    }


def _page_summary(
    lines: list[TextLine],
    records: list[LineMetrics],
    collisions: list[dict[str, Any]],
    page_width: float,
) -> dict[str, Any]:
    changed = [record for record in records if record.changed]
    body = [
        record
        for record in changed
        if record.orig_ink and (record.orig_ink[2] - record.orig_ink[0]) >= 0.35 * page_width
    ]
    height_ratios = [record.ink_height_ratio for record in body if record.ink_height_ratio]
    right_drift = [abs(record.right_delta) for record in changed if record.right_delta is not None]
    baseline_deltas = [
        abs(record.baseline_proxy_delta) for record in changed if record.baseline_proxy_delta is not None
    ]

    rhythm_max_gap_delta = None
    body_sorted = [record for record in body if record.baseline_proxy_delta is not None]
    body_sorted.sort(key=lambda record: record.bbox[1])
    if len(body_sorted) >= 2:
        deltas = []
        for upper, lower in zip(body_sorted, body_sorted[1:]):
            deltas.append(abs(lower.baseline_proxy_delta - upper.baseline_proxy_delta))
        rhythm_max_gap_delta = round(max(deltas), 3) if deltas else None

    flag_counts: dict[str, int] = {}
    for record in records:
        for flag in record.flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    return {
        "total_lines": len(records),
        "changed_lines": len(changed),
        "flagged_lines": sum(1 for record in records if record.flags),
        "body_ink_height_ratio": _distribution(height_ratios),
        "right_edge_drift_pt": _distribution(right_drift),
        "baseline_proxy_delta_pt": _distribution(baseline_deltas),
        "rhythm_max_gap_delta_pt": rhythm_max_gap_delta,
        "clearance_collisions": len(collisions),
        "flag_counts": flag_counts,
    }


def _record_to_json(record: LineMetrics) -> dict[str, Any]:
    def rounded(value: float | None) -> float | None:
        return round(value, 3) if value is not None else None

    return {
        "index": record.index,
        "text": record.text_preview,
        "bbox": list(record.bbox),
        "changed": record.changed,
        "diff_px": record.diff_px,
        "orig_ink": [round(v, 2) for v in record.orig_ink] if record.orig_ink else None,
        "new_ink": [round(v, 2) for v in record.new_ink] if record.new_ink else None,
        "top_delta": rounded(record.top_delta),
        "bottom_delta": rounded(record.bottom_delta),
        "left_delta": rounded(record.left_delta),
        "right_delta": rounded(record.right_delta),
        "ink_height_ratio": rounded(record.ink_height_ratio),
        "baseline_proxy_delta": rounded(record.baseline_proxy_delta),
        "flags": record.flags,
    }


def compare_page(
    orig_page: fitz.Page,
    new_page: fitz.Page,
    page_no: int,
    zoom: float,
) -> tuple[dict[str, Any], list[TextLine], list[LineMetrics]]:
    lines = _extract_lines(orig_page, page_no)
    raster_orig = PageRaster(orig_page, zoom)
    raster_new = PageRaster(new_page, zoom)
    size_match = raster_orig.width == raster_new.width and raster_orig.height == raster_new.height
    if not size_match:
        return (
            {
                "page": page_no + 1,
                "page_size_match": False,
                "lines": [],
                "collisions": [],
                "summary": {"error": "page geometry mismatch"},
            },
            lines,
            [],
        )

    records = _measure_lines(lines, raster_orig, raster_new, zoom)
    collisions = _gap_band_metrics(lines, records, raster_orig, raster_new, zoom)
    summary = _page_summary(lines, records, collisions, float(orig_page.rect.width))
    xband_orig = _page_xband_mean_pt(orig_page, page_no, zoom)
    xband_new = _page_xband_mean_pt(new_page, page_no, zoom)
    summary["xband_ratio"] = round(xband_new / xband_orig, 4) if xband_orig and xband_new else None
    payload = {
        "page": page_no + 1,
        "page_size_match": True,
        "summary": summary,
        "collisions": collisions,
        "lines": [_record_to_json(record) for record in records],
    }
    return payload, lines, records


def _write_overlay(
    new_doc: fitz.Document,
    page_no: int,
    records: list[LineMetrics],
    zoom: float,
    out_path: Path,
) -> None:
    page = new_doc[page_no]
    shape = page.new_shape()
    for record in records:
        rect = fitz.Rect(record.bbox)
        if record.flags:
            shape.draw_rect(rect)
            shape.finish(color=(0.9, 0.1, 0.1), width=0.8)
        elif record.changed:
            shape.draw_rect(rect)
            shape.finish(color=(0.95, 0.65, 0.1), width=0.4)
    shape.commit()
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pix.save(out_path)


def emulate_live_plan(doc: fitz.Document, plan: dict[str, Any]) -> None:
    """Apply a live page plan to `doc` the way the compositor would.

    Erase every safe region (white fill, mirroring the canvas pixel erase),
    then draw each run at its baseline matrix with fontSize/scaleX/color.
    """
    page = doc[int(plan["pageIndex"])]
    for region in plan.get("safeRegions", []):
        rect = fitz.Rect(region["bboxPdf"])
        pad = float(region.get("erasePaddingPxAt1x", 2))
        rect = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
        page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)

    font_names: dict[str, str] = {}
    for run in plan.get("drawRuns", []):
        font_path = run["fontPath"]
        font_names.setdefault(font_path, f"VVLive{len(font_names)}")

    for path, name in font_names.items():
        try:
            page.insert_font(fontname=name, fontfile=path)
        except Exception:
            pass

    for run in plan.get("drawRuns", []):
        matrix = run["matrixPdf"]
        point = fitz.Point(float(matrix[4]), float(matrix[5]))
        color = run.get("color", [0, 0, 0, 1])
        rgb = (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)
        kwargs = {
            "fontname": font_names[run["fontPath"]],
            "fontfile": run["fontPath"],
            "fontsize": float(run["fontSize"]),
            "color": rgb,
            "overlay": True,
        }
        scale_x = float(run.get("scaleX", 1.0))
        if abs(scale_x - 1.0) > 0.001:
            try:
                page.insert_text(point, run["text"], morph=(point, fitz.Matrix(scale_x, 1.0)), **kwargs)
                continue
            except Exception:
                pass
        page.insert_text(point, run["text"], **kwargs)


def run_compare(
    original: Path,
    compared: Path,
    pages: list[int] | None,
    out_dir: Path,
    zoom: float,
    overlays: bool,
    mode_label: str = "export",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    orig_doc = fitz.open(original)
    new_doc = fitz.open(compared)
    try:
        page_numbers = pages if pages is not None else list(range(min(orig_doc.page_count, new_doc.page_count)))
        page_payloads = []
        for page_no in page_numbers:
            payload, _, records = compare_page(orig_doc[page_no], new_doc[page_no], page_no, zoom)
            page_payloads.append(payload)
            if overlays and (payload["summary"].get("flagged_lines") or payload["summary"].get("changed_lines")):
                overlay_doc = fitz.open(compared)
                try:
                    _write_overlay(overlay_doc, page_no, records, zoom, out_dir / f"page{page_no + 1}_overlay.png")
                finally:
                    overlay_doc.close()
        report = _build_report(original, compared, mode_label, zoom, page_payloads)
    finally:
        orig_doc.close()
        new_doc.close()

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def run_live(
    original: Path,
    font: Path,
    cjk_fallback: Path | None,
    pages: list[int] | None,
    out_dir: Path,
    zoom: float,
    overlays: bool,
    mode: str,
) -> dict[str, Any]:
    from .live_plan import LivePlanOptions, build_live_page_plan

    out_dir.mkdir(parents=True, exist_ok=True)
    orig_doc = fitz.open(original)
    try:
        page_numbers = pages if pages is not None else list(range(orig_doc.page_count))
        page_payloads = []
        for page_no in page_numbers:
            plan = build_live_page_plan(
                LivePlanOptions(
                    input_pdf=original,
                    target_font=font,
                    page_index=page_no,
                    cjk_fallback=cjk_fallback,
                    mode=mode,
                )
            )
            if plan.get("status") in {"original", "error"}:
                page_payloads.append(
                    {
                        "page": page_no + 1,
                        "live_status": plan.get("status"),
                        "summary": {"skipped": True, "reason": plan.get("error", "page left original")},
                    }
                )
                continue

            emulated = fitz.open(original)
            try:
                emulate_live_plan(emulated, plan)
                payload, _, records = compare_page(orig_doc[page_no], emulated[page_no], page_no, zoom)
                payload["live_status"] = plan.get("status")
                payload["live_draw_runs"] = len(plan.get("drawRuns", []))
                payload["live_unsafe_regions"] = len(plan.get("unsafeRegions", []))
                page_payloads.append(payload)
                if overlays:
                    _write_overlay(emulated, page_no, records, zoom, out_dir / f"page{page_no + 1}_live_overlay.png")
            finally:
                emulated.close()
        report = _build_report(original, Path(f"live-plan({font.name})"), "live-emulated", zoom, page_payloads)
    finally:
        orig_doc.close()

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def _build_report(
    original: Path,
    compared: Path,
    mode_label: str,
    zoom: float,
    page_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    totals = {
        "pages": len(page_payloads),
        "changed_lines": sum(payload["summary"].get("changed_lines", 0) for payload in page_payloads),
        "flagged_lines": sum(payload["summary"].get("flagged_lines", 0) for payload in page_payloads),
        "clearance_collisions": sum(payload["summary"].get("clearance_collisions", 0) for payload in page_payloads),
    }
    flag_totals: dict[str, int] = {}
    for payload in page_payloads:
        for flag, count in payload["summary"].get("flag_counts", {}).items():
            flag_totals[flag] = flag_totals.get(flag, 0) + count
    totals["flag_counts"] = flag_totals
    return {
        "meta": {
            "original": str(original),
            "compared": str(compared),
            "mode": mode_label,
            "zoom": zoom,
            "ink_threshold": INK_THRESHOLD,
            "provisional_notes": PROVISIONAL_NOTES,
        },
        "totals": totals,
        "pages": page_payloads,
    }


def _parse_pages(value: str | None) -> list[int] | None:
    if not value:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            pages.update(range(int(start) - 1, int(end)))
        else:
            pages.add(int(token) - 1)
    return sorted(pages)


def print_summary(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print(
        f"[visual-verify:{report['meta']['mode']}] pages={totals['pages']} "
        f"changed={totals['changed_lines']} flagged={totals['flagged_lines']} "
        f"gap_collisions={totals['clearance_collisions']} flags={totals['flag_counts']}"
    )
    for payload in report["pages"]:
        summary = payload["summary"]
        if summary.get("skipped"):
            print(f"  page {payload['page']}: skipped ({summary.get('reason', '')})")
            continue
        ratio = summary.get("body_ink_height_ratio")
        ratio_text = f"body_h_ratio median={ratio['median']} [{ratio['p10']}, {ratio['p90']}]" if ratio else "no body lines changed"
        ratio_text += f" xband={summary.get('xband_ratio')}"
        print(
            f"  page {payload['page']}: changed={summary.get('changed_lines', 0)} "
            f"flagged={summary.get('flagged_lines', 0)} {ratio_text} "
            f"rhythm_max={summary.get('rhythm_max_gap_delta_pt')} collisions={summary.get('clearance_collisions', 0)}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="refont.visual_verify", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    compare_parser = sub.add_parser("compare", help="Compare original vs refonted PDF")
    compare_parser.add_argument("original")
    compare_parser.add_argument("refonted")
    compare_parser.add_argument("--pages", help='e.g. "1-10,15"')
    compare_parser.add_argument("--out", required=True)
    compare_parser.add_argument("--zoom", type=float, default=4.0)
    compare_parser.add_argument("--overlays", action="store_true")

    live_parser = sub.add_parser("live", help="Verify emulated live page plans")
    live_parser.add_argument("original")
    live_parser.add_argument("--font", required=True)
    live_parser.add_argument("--cjk-fallback")
    live_parser.add_argument("--pages", help='e.g. "1-10,15"')
    live_parser.add_argument("--out", required=True)
    live_parser.add_argument("--zoom", type=float, default=4.0)
    live_parser.add_argument("--mode", choices=["conservative", "normal"], default="conservative")
    live_parser.add_argument("--overlays", action="store_true")

    args = parser.parse_args(argv)
    pages = _parse_pages(args.pages)

    if args.command == "compare":
        report = run_compare(
            Path(args.original).expanduser().resolve(),
            Path(args.refonted).expanduser().resolve(),
            pages,
            Path(args.out).expanduser().resolve(),
            args.zoom,
            args.overlays,
        )
    else:
        report = run_live(
            Path(args.original).expanduser().resolve(),
            Path(args.font).expanduser().resolve(),
            Path(args.cjk_fallback).expanduser().resolve() if args.cjk_fallback else None,
            pages,
            Path(args.out).expanduser().resolve(),
            args.zoom,
            args.overlays,
            args.mode,
        )
    print_summary(report)


if __name__ == "__main__":
    main()
