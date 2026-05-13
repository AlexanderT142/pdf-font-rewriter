from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import uharfbuzz as hb

from .models import FitResult, FontInfo, FontSegment, FontVisualProfile, ShapedMeasure


@dataclass(frozen=True)
class ShapingResult:
    advance: float
    glyph_count: int


@lru_cache(maxsize=64)
def _face_for_font(path: str, font_index: int) -> hb.Face:
    blob = hb.Blob.from_file_path(path)
    return hb.Face(blob, font_index)


def shape_line(text: str, font: FontInfo, font_size: float) -> ShapingResult:
    if not text:
        return ShapingResult(advance=0.0, glyph_count=0)

    face = _face_for_font(str(font.path), font.font_index)
    hb_font = hb.Font(face)
    # Scaling by font size in 26.6 fixed-point yields advances in PDF points.
    hb_font.scale = (int(font_size * 64), int(font_size * 64))

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf)

    advance = sum(position.x_advance for position in buf.glyph_positions) / 64.0
    return ShapingResult(advance=advance, glyph_count=len(buf.glyph_positions))


@lru_cache(maxsize=8192)
def measure_shaped_text_du(
    text: str,
    font_id: str,
    path: str,
    font_index: int,
    upem: int,
    script: str = "Latn",
    direction: str = "ltr",
) -> ShapedMeasure:
    if not text:
        return ShapedMeasure(
            font_id=font_id,
            text=text,
            script=script,
            advance_du=0.0,
            ink_x_min_du=0.0,
            ink_x_max_du=0.0,
            ink_y_min_du=0.0,
            ink_y_max_du=0.0,
            glyph_count=0,
            cluster_count=0,
            has_notdef=False,
        )

    face = _face_for_font(path, font_index)
    hb_font = hb.Font(face)
    hb_font.scale = (upem, upem)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.direction = direction
    if script:
        buf.script = script
    else:
        buf.guess_segment_properties()
    hb.shape(hb_font, buf)

    cursor_x = 0.0
    ink_x_min = float("inf")
    ink_x_max = float("-inf")
    ink_y_min = float("inf")
    ink_y_max = float("-inf")
    has_ink = False
    has_notdef = False

    for info, position in zip(buf.glyph_infos, buf.glyph_positions):
        gid = int(info.codepoint)
        has_notdef = has_notdef or gid == 0
        extents = hb_font.get_glyph_extents(gid)
        if extents is not None:
            gx0 = cursor_x + position.x_offset + extents.x_bearing
            gx1 = gx0 + extents.width
            gy0 = position.y_offset + extents.y_bearing + extents.height
            gy1 = position.y_offset + extents.y_bearing
            ink_x_min = min(ink_x_min, gx0, gx1)
            ink_x_max = max(ink_x_max, gx0, gx1)
            ink_y_min = min(ink_y_min, gy0, gy1)
            ink_y_max = max(ink_y_max, gy0, gy1)
            has_ink = True
        cursor_x += position.x_advance

    if not has_ink:
        ink_x_min = ink_x_max = ink_y_min = ink_y_max = 0.0

    return ShapedMeasure(
        font_id=font_id,
        text=text,
        script=script,
        advance_du=cursor_x,
        ink_x_min_du=ink_x_min,
        ink_x_max_du=ink_x_max,
        ink_y_min_du=ink_y_min,
        ink_y_max_du=ink_y_max,
        glyph_count=len(buf.glyph_infos),
        cluster_count=len({info.cluster for info in buf.glyph_infos}),
        has_notdef=has_notdef,
    )


def measure_profile_text_du(text: str, profile: FontVisualProfile, script: str, direction: str = "ltr") -> ShapedMeasure:
    return measure_shaped_text_du(
        text=text,
        font_id=profile.font_id,
        path=str(profile.path),
        font_index=profile.face_index,
        upem=profile.upem,
        script=script,
        direction=direction,
    )


def nominal_size_from_height(original_height: float, font: FontInfo) -> float:
    vertical_units = max(1, font.ascender - font.descender)
    return max(1.0, original_height * font.upem / vertical_units)


def compute_line_fit(
    original_advance: float,
    original_height: float,
    segments: list[FontSegment],
    mode: str = "conservative",
) -> FitResult:
    if original_advance <= 0 or original_height <= 0 or not segments:
        return FitResult(
            font_size=max(1.0, original_height),
            scale_x=1.0,
            method="unsafe",
            target_advance=0.0,
            segments=segments,
            unsafe_reason="empty or invalid geometry",
        )

    primary_font = segments[0].font
    nominal_size = nominal_size_from_height(original_height, primary_font)
    contains_cjk = any(segment.script == "cjk" for segment in segments)
    target_advance = _shape_segments(segments, nominal_size)
    if target_advance <= 0:
        return FitResult(
            font_size=nominal_size,
            scale_x=1.0,
            method="unsafe",
            target_advance=target_advance,
            segments=segments,
            unsafe_reason="target font produced no advance",
        )

    scale_x = original_advance / target_advance
    ideal_min, ideal_max, hard_min, hard_max = _fit_bounds(mode, contains_cjk)

    if ideal_min <= scale_x <= ideal_max:
        return FitResult(
            font_size=nominal_size,
            scale_x=scale_x,
            method="scale",
            target_advance=target_advance,
            segments=segments,
        )

    if hard_min <= scale_x <= hard_max:
        requested_size = nominal_size * scale_x
        adjusted_size = min(max(requested_size, nominal_size - 1.0), nominal_size + 1.0)
        adjusted_advance = _shape_segments(segments, adjusted_size)
        if adjusted_advance > 0:
            adjusted_scale = original_advance / adjusted_advance
            if ideal_min <= adjusted_scale <= ideal_max:
                return FitResult(
                    font_size=adjusted_size,
                    scale_x=adjusted_scale,
                    method="size_adjust",
                    target_advance=adjusted_advance,
                    segments=segments,
                )

    return FitResult(
        font_size=nominal_size,
        scale_x=scale_x,
        method="unsafe",
        target_advance=target_advance,
        segments=segments,
        unsafe_reason=f"replacement text does not fit within original geometry (scaleX={scale_x:.3f})",
    )


def _shape_segments(segments: list[FontSegment], font_size: float) -> float:
    return sum(shape_line(segment.text, segment.font, font_size).advance for segment in segments)


def _fit_bounds(mode: str, contains_cjk: bool) -> tuple[float, float, float, float]:
    if contains_cjk:
        return (0.95, 1.05, 0.90, 1.10)
    if mode == "normal":
        return (0.90, 1.10, 0.85, 1.15)
    return (0.92, 1.08, 0.85, 1.15)
