from __future__ import annotations

from collections import OrderedDict

import fitz

from .models import FontSegment, TextLine
from .shaper import shape_line


def insert_replacement_text(page: fitz.Page, safe_lines: list[TextLine]) -> None:
    if not safe_lines:
        return

    font_names = _register_fonts(page, safe_lines)
    for line in safe_lines:
        fit = line.fit_result
        if not fit or not fit.safe:
            continue

        color = rgb_from_pymupdf(line.runs[0].color if line.runs else 0)
        origin_x = _line_origin_x(line)
        baseline_y = line.baseline_y
        cursor_x = origin_x

        for index, segment in enumerate(fit.segments):
            font_name = font_names[str(segment.font.path)]
            point = fitz.Point(cursor_x, baseline_y)
            font_size = fit.segment_sizes[index] if index < len(fit.segment_sizes) else fit.font_size
            _insert_segment(page, point, segment, font_name, font_size, fit.scale_x, color)
            cursor_x += shape_line(segment.text, segment.font, font_size).advance * fit.scale_x


def _line_origin_x(line: TextLine) -> float:
    fit = line.fit_result
    decision = fit.visual_decision if fit else None
    if not fit or not decision:
        return min((run.origin[0] for run in line.runs), default=line.bbox[0])
    scaled_advance = fit.target_advance * fit.scale_x
    if decision.anchor_mode.value == "center":
        return decision.anchor_x - scaled_advance / 2
    if decision.anchor_mode.value == "right":
        return decision.anchor_x - scaled_advance
    return decision.anchor_x


def _register_fonts(page: fitz.Page, safe_lines: list[TextLine]) -> dict[str, str]:
    ordered_paths: OrderedDict[str, str] = OrderedDict()
    for line in safe_lines:
        if not line.fit_result:
            continue
        for segment in line.fit_result.segments:
            ordered_paths.setdefault(str(segment.font.path), f"Refont{len(ordered_paths)}")

    for path, name in ordered_paths.items():
        try:
            page.insert_font(fontname=name, fontfile=path)
        except Exception:
            # insert_text can still receive fontfile; keep the name mapping.
            pass
    return dict(ordered_paths)


def _insert_segment(
    page: fitz.Page,
    point: fitz.Point,
    segment: FontSegment,
    font_name: str,
    font_size: float,
    scale_x: float,
    color: tuple[float, float, float],
) -> None:
    kwargs = {
        "fontname": font_name,
        "fontfile": str(segment.font.path),
        "fontsize": font_size,
        "color": color,
        "overlay": True,
    }
    if abs(scale_x - 1.0) > 0.001:
        try:
            page.insert_text(point, segment.text, morph=(point, fitz.Matrix(scale_x, 1.0)), **kwargs)
            return
        except Exception:
            pass
    page.insert_text(point, segment.text, **kwargs)


def rgb_from_pymupdf(value: object) -> tuple[float, float, float]:
    if isinstance(value, int):
        return (
            ((value >> 16) & 0xFF) / 255.0,
            ((value >> 8) & 0xFF) / 255.0,
            (value & 0xFF) / 255.0,
        )
    if isinstance(value, (tuple, list)):
        if len(value) >= 3:
            vals = [float(value[0]), float(value[1]), float(value[2])]
            if any(component > 1.0 for component in vals):
                vals = [component / 255.0 for component in vals]
            return (max(0.0, min(vals[0], 1.0)), max(0.0, min(vals[1], 1.0)), max(0.0, min(vals[2], 1.0)))
        if len(value) == 1:
            gray = max(0.0, min(float(value[0]), 1.0))
            return (gray, gray, gray)
    return (0.0, 0.0, 0.0)
