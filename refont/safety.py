from __future__ import annotations

from collections import Counter

import fitz

from .font_utils import build_visual_profile_chain, is_cjk_codepoint, is_private_use, missing_codepoints, segment_by_font_coverage
from .ink_sampler import PageInkSampler
from .inserter import rgb_from_pymupdf
from .models import FontInfo, PageIndex, RectTuple, TextLine, TextRun
from .region_policy import apply_region_coherence_policy
from .text_layer_validator import (
    line_text_layer_rejection_reason,
    native_text_mapping_rejection_reason,
    validate_page_text_layer,
)
from .visual_fit import analyze_page_visual_stats, fit_visual_geometry


TEXT_BBOX_TYPES = {"fill-text", "stroke-text", "ignore-text"}


def analyze_page_safety(page: fitz.Page, page_index: PageIndex, font_chain: list[FontInfo], mode: str) -> None:
    if page_index.classification not in {"native", "hybrid"}:
        return

    bboxlog = _safe_bboxlog(page)
    widget_rects = _widget_rects(page)
    visual_profiles = build_visual_profile_chain(font_chain)
    validate_page_text_layer(page, page_index, mode)
    sampler = PageInkSampler(page)
    page_visual_stats = analyze_page_visual_stats(page.rect, page_index.lines, sampler)

    for line in page_index.lines:
        reasons: list[str] = []

        if line.direction in {"rtl", "ttb", "rotated"}:
            reasons.append(f"{line.direction} text is out of scope")
        elif line.direction == "unknown":
            reasons.append("unknown text direction")

        if _line_intersects_any(line.bbox, widget_rects):
            reasons.append("text appears to be part of a form field or widget")

        for run in line.runs:
            reasons.extend(_run_safety_reasons(run, bboxlog))

        unicode_reason = _unicode_reliability_reason(line)
        if unicode_reason:
            reasons.append(unicode_reason)

        text_layer_reason = line_text_layer_rejection_reason(line)
        if text_layer_reason:
            reasons.append(text_layer_reason)

        native_mapping_reason = native_text_mapping_rejection_reason(line)
        if native_mapping_reason:
            reasons.append(native_mapping_reason)

        missing = missing_codepoints(line.text, font_chain)
        if missing:
            preview = ", ".join(f"U+{codepoint:04X}" for codepoint in sorted(set(missing))[:8])
            reasons.append(f"missing glyph coverage ({preview})")

        # Paint/style mixing is appended AFTER the fit is computed: these
        # lines must still carry a fit_result so the region coherence pass
        # sees them as hard failures and skips the whole paragraph, instead
        # of converting the lines around them (a mixed-typeface paragraph).
        paint_reasons = _mixed_paint_reasons(line, mode)

        segments = segment_by_font_coverage(line.text, font_chain) if not missing else []
        if segments and not reasons:
            fit = fit_visual_geometry(
                line=line,
                segments=segments,
                visual_profiles=visual_profiles,
                page_rect=page.rect,
                page_stats=page_visual_stats,
                mode=mode,
                sampler=sampler,
            )
            line.fit_result = fit
            if not fit.safe:
                reasons.append(fit.unsafe_reason)
        reasons.extend(paint_reasons)

        deduped = _dedupe_preserve_order(reasons)
        if deduped:
            line.safety = "unsafe"
            line.unsafe_reasons = deduped
        else:
            line.safety = "safe"
            line.unsafe_reasons = []

    apply_region_coherence_policy(
        page_index=page_index,
        page_rect=page.rect,
        page_stats=page_visual_stats,
        mode=mode,
    )

    page_index.safe_line_count = sum(1 for line in page_index.lines if line.safety == "safe")
    page_index.unsafe_line_count = sum(1 for line in page_index.lines if line.safety == "unsafe")


def summarize_unsafe_reasons(lines: list[TextLine]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for line in lines:
        for reason in line.unsafe_reasons:
            counter[reason] += 1
    return dict(counter)


def _run_safety_reasons(run: TextRun, bboxlog: list[tuple[str, fitz.Rect]]) -> list[str]:
    reasons: list[str] = []

    if run.source == "invisible-ocr" or run.opacity <= 0:
        reasons.append("invisible OCR layer")

    if run.seqno >= 0 and bboxlog:
        run_rect = fitz.Rect(run.bbox)
        for later_seqno, (entry_type, entry_rect) in enumerate(bboxlog[run.seqno + 1 :], start=run.seqno + 1):
            if entry_type in TEXT_BBOX_TYPES:
                continue
            if entry_rect.is_empty or entry_rect.get_area() <= 0:
                continue
            if run_rect.intersects(entry_rect):
                reasons.append(f"later {entry_type} overlaps text at seqno {later_seqno}")
                break

    return reasons


def _mixed_paint_reasons(line: TextLine, mode: str) -> list[str]:
    """Lines whose runs paint differently cannot be reproduced uniformly.

    The inserter draws one color per line, so materially mixed colors (e.g.
    a colored link inside black text) would be flattened — always unsafe.
    Mixed fonts/styles within one script (italic or bold phrases inside a
    roman line; the source styles are often distinguishable only by their
    subset font name) would be flattened to the single target face — unsafe
    in conservative mode. Font changes ACROSS scripts (a Latin font plus a
    CJK font in one line) are ordinary typesetting, not style mixing.
    """
    runs = [run for run in line.runs if run.text.strip()]
    if len(runs) <= 1:
        return []

    reasons: list[str] = []
    colors = [rgb_from_pymupdf(run.color) for run in runs]
    base = colors[0]
    if any(max(abs(c[i] - base[i]) for i in range(3)) > 0.12 for c in colors[1:]):
        reasons.append("line mixes text colors")

    if mode == "conservative":
        fonts_by_script: dict[str, set[str]] = {}
        flags_by_script: dict[str, set[tuple[str, ...]]] = {}
        for run in runs:
            script = _run_script_class(run.text)
            fonts_by_script.setdefault(script, set()).add(run.font_name)
            flags_by_script.setdefault(script, set()).add(tuple(sorted(run.flags)))
        if any(len(fonts) > 1 for fonts in fonts_by_script.values()) or any(
            len(flags) > 1 for flags in flags_by_script.values()
        ):
            reasons.append("line mixes fonts or styles")

    return reasons


def _run_script_class(text: str) -> str:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return "latin"
    cjk = sum(1 for char in visible if is_cjk_codepoint(ord(char)))
    return "cjk" if cjk >= len(visible) / 2 else "latin"


def _unicode_reliability_reason(line: TextLine) -> str:
    if not line.text.strip() and _area(line.bbox) > 0.01:
        return "unreliable Unicode mapping"
    for char in line.text:
        codepoint = ord(char)
        if char == "\uFFFD" or is_private_use(codepoint):
            return "unreliable Unicode mapping"
    return ""


def _safe_bboxlog(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
    try:
        raw = page.get_bboxlog()
    except Exception:
        return []

    entries: list[tuple[str, fitz.Rect]] = []
    for entry in raw:
        parsed = _parse_bboxlog_entry(entry)
        if parsed:
            entries.append(parsed)
    return entries


def _parse_bboxlog_entry(entry: object) -> tuple[str, fitz.Rect] | None:
    if not isinstance(entry, (tuple, list)) or not entry:
        return None

    entry_type = str(entry[0])
    rect_value: object
    if len(entry) >= 2 and isinstance(entry[1], (tuple, list, fitz.Rect)):
        rect_value = entry[1]
    elif len(entry) >= 5:
        rect_value = entry[1:5]
    else:
        return None

    try:
        return (entry_type, fitz.Rect(rect_value))
    except Exception:
        return None


def _widget_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    try:
        widgets = page.widgets()
        if widgets:
            rects.extend(fitz.Rect(widget.rect) for widget in widgets)
    except Exception:
        pass
    return rects


def _line_intersects_any(bbox: RectTuple, rects: list[fitz.Rect]) -> bool:
    line_rect = fitz.Rect(bbox)
    return any(line_rect.intersects(rect) for rect in rects)


def _area(rect: RectTuple) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
