from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import fitz

from .font_utils import is_cjk_codepoint
from .ink_sampler import PageInkSampler
from .models import (
    AnchorMode,
    CharGeometry,
    CharVisualStats,
    FitResult,
    FontInfo,
    FontSegment,
    FontVisualProfile,
    LineRole,
    OriginalLineVisual,
    RectTuple,
    SegmentFitPlan,
    TextLine,
    VisualFitDecision,
    VisualFitThresholds,
    VisualMetricKind,
)
from .shaper import measure_profile_text_du

# Assumed ratio of original CJK ideograph ink height to the nominal font
# size, used when no trustworthy observed metric is available. CJK fonts
# draw ideographs inside an "ideographic character face" of roughly
# 0.86-0.93 em (Hiragino Sans GB measures 0.927, Noto CJK ~0.88); assuming
# 1.00 sized CJK segments ~8% too large relative to the source.
CJK_INK_RATIO = 0.91


@dataclass(frozen=True)
class PageVisualStats:
    width_pt: float
    height_pt: float
    body_line_height_pt: float | None
    body_baseline_gap_pt: float | None
    body_xheight_pt: float | None


def analyze_page_visual_stats(
    page_rect: fitz.Rect,
    lines: list[TextLine],
    sampler: "PageInkSampler | None" = None,
) -> PageVisualStats:
    body_like_heights: list[float] = []
    body_like_xheights: list[float] = []
    baselines: list[float] = []

    for line in lines:
        visual = build_original_line_visual(line, page_rect, sampler)
        text = line.text.strip()
        if not text:
            continue
        width_ratio = (line.bbox[2] - line.bbox[0]) / max(float(page_rect.width), 1.0)
        if 0.25 <= width_ratio <= 0.95 and visual.orig_ink_height_pt > 3:
            body_like_heights.append(visual.orig_ink_height_pt)
            baselines.append(line.baseline_y)
            if visual.char_stats.lower_mid_height_pt:
                body_like_xheights.append(visual.char_stats.lower_mid_height_pt)

    baseline_gaps = [
        b - a
        for a, b in zip(sorted(baselines), sorted(baselines)[1:])
        if 4 <= b - a <= 30
    ]

    return PageVisualStats(
        width_pt=float(page_rect.width),
        height_pt=float(page_rect.height),
        body_line_height_pt=_median_or_none(body_like_heights),
        body_baseline_gap_pt=_median_or_none(baseline_gaps),
        body_xheight_pt=_median_or_none(body_like_xheights),
    )


def build_original_line_visual(
    line: TextLine,
    page_rect: fitz.Rect,
    sampler: "PageInkSampler | None" = None,
) -> OriginalLineVisual:
    chars = _line_chars(line)
    nonspace_chars = [char for char in chars if char.char.strip()]
    nonspace_bbox = _union_rects([char.bbox for char in nonspace_chars]) if nonspace_chars else line.bbox
    baseline_y = line.baseline_y
    # Vertical extents prefer real painted ink over char font boxes, so the
    # overflow check compares target ink against source ink, not against the
    # (much taller) ascender/descender box.
    ink_top_y = nonspace_bbox[1]
    ink_bottom_y = nonspace_bbox[3]
    if sampler is not None:
        extent = sampler.line_ink_extent_pt(nonspace_bbox)
        if extent is not None and extent[1] > extent[0]:
            ink_top_y, ink_bottom_y = extent
    orig_top = max(0.0, baseline_y - ink_top_y)
    orig_bottom = max(0.0, ink_bottom_y - baseline_y)
    anchor_mode = _anchor_mode(line, page_rect)
    anchor_x = _anchor_x(line, anchor_mode)

    return OriginalLineVisual(
        bbox=line.bbox,
        nonspace_bbox=nonspace_bbox,
        baseline_y=baseline_y,
        orig_top_pt=orig_top,
        orig_bottom_pt=orig_bottom,
        orig_ink_height_pt=max(0.0, ink_bottom_y - ink_top_y),
        orig_advance_pt=max(0.0, nonspace_bbox[2] - nonspace_bbox[0]),
        anchor_mode=anchor_mode,
        anchor_x=anchor_x,
        char_stats=_char_visual_stats(nonspace_chars, line, sampler),
    )


def classify_line_role(
    line: TextLine,
    original: OriginalLineVisual,
    page_stats: PageVisualStats,
) -> tuple[LineRole, float]:
    text = line.text.strip()
    if not text:
        return (LineRole.UNKNOWN, 0.0)

    visible_count = max(1, sum(1 for char in text if not char.isspace()))
    alpha_count = max(1, sum(1 for char in text if char.isalpha()))
    cjk_ratio = sum(1 for char in text if is_cjk_codepoint(ord(char))) / visible_count
    latin_ratio = sum(1 for char in text if "A" <= char.upper() <= "Z") / visible_count
    upper_ratio = sum(1 for char in text if char.isupper()) / alpha_count
    digit_ratio = sum(1 for char in text if char.isdigit()) / visible_count
    width_ratio = original.orig_advance_pt / max(page_stats.width_pt, 1.0)
    line_height = original.orig_ink_height_pt
    body_height = page_stats.body_line_height_pt or line_height
    in_header = line.bbox[1] < page_stats.height_pt * 0.12
    in_footer = line.bbox[3] > page_stats.height_pt * 0.88

    if digit_ratio >= 0.5 and visible_count <= 12 and width_ratio <= 0.18:
        return (LineRole.PAGE_NUMBER, 0.86 if in_header or in_footer else 0.68)
    if in_header and visible_count <= 60 and width_ratio <= 0.55:
        return (LineRole.RUNNING_HEADER, 0.70)
    if cjk_ratio >= 0.65:
        return (LineRole.CJK_BODY, 0.86)
    if cjk_ratio >= 0.20 and latin_ratio >= 0.20:
        return (LineRole.MIXED_LATIN_CJK, 0.78)
    if line_height <= body_height * 0.85 and (line.bbox[1] > page_stats.height_pt * 0.45 or visible_count <= 90):
        return (LineRole.FOOTNOTE, 0.68)
    if width_ratio >= 0.42 and visible_count >= 35 and line_height <= body_height * 1.35:
        return (LineRole.BODY, 0.80)
    if line_height >= body_height * 1.20 or (upper_ratio >= 0.70 and visible_count <= 80):
        return (LineRole.HEADING, 0.74)
    if width_ratio >= 0.25 and 0.70 * body_height <= line_height <= 1.30 * body_height:
        return (LineRole.BODY, 0.82)
    return (LineRole.UNKNOWN, 0.45)


def fit_visual_geometry(
    line: TextLine,
    segments: list[FontSegment],
    visual_profiles: dict[str, FontVisualProfile],
    page_rect: fitz.Rect,
    page_stats: PageVisualStats,
    mode: str = "conservative",
    thresholds: VisualFitThresholds | None = None,
    sampler: "PageInkSampler | None" = None,
) -> FitResult:
    thresholds = thresholds or VisualFitThresholds(strict_unknown=(mode == "conservative"))
    original = build_original_line_visual(line, page_rect, sampler)
    role, confidence = classify_line_role(line, original, page_stats)

    reject_reasons: list[str] = []
    if thresholds.strict_unknown and role == LineRole.UNKNOWN:
        reject_reasons.append("unknown visual line role")
    if confidence < thresholds.min_role_confidence:
        reject_reasons.append(f"low visual role confidence ({confidence:.2f})")

    plan = _build_segment_plans(line, segments, visual_profiles, original, role)
    reject_reasons.extend(plan.reject_reasons)

    if plan.segments and not reject_reasons:
        scale_x = original.orig_advance_pt / plan.unscaled_advance_pt if plan.unscaled_advance_pt > 0 else 1.0
        lower, upper = _role_scale_limits(role, thresholds)
        hard_lower, hard_upper = thresholds.hard_scale
        if lower <= scale_x <= upper:
            pass
        elif hard_lower <= scale_x <= hard_upper:
            adjusted_plan = _rescale_plan(plan, scale_x, visual_profiles)
            adjusted_scale = original.orig_advance_pt / adjusted_plan.unscaled_advance_pt if adjusted_plan.unscaled_advance_pt > 0 else scale_x
            if lower <= adjusted_scale <= upper:
                plan = adjusted_plan
                scale_x = adjusted_scale
            else:
                reject_reasons.append(f"visual scale outside {role.value} bounds (scaleX={scale_x:.3f})")
        else:
            reject_reasons.append(f"replacement text does not fit visual geometry (scaleX={scale_x:.3f})")

        max_overflow = min(0.75, max(0.25, original.orig_ink_height_pt * 0.10))
        if plan.target_top_pt - original.orig_top_pt > max_overflow:
            reject_reasons.append("target ink overflows original line top")
        if plan.target_bottom_pt - original.orig_bottom_pt > max_overflow:
            reject_reasons.append("target ink overflows original line bottom")
    else:
        scale_x = None

    safe = not reject_reasons
    decision = VisualFitDecision(
        safe=safe,
        role=role,
        confidence=confidence,
        metric_used=plan.metric_used,
        original_metric_pt=plan.original_metric_pt,
        target_metric_du=plan.target_metric_du,
        raw_size_pt=plan.raw_size_pt,
        final_size_pt=plan.final_size_pt,
        scale_x=scale_x,
        target_top_pt=plan.target_top_pt,
        target_bottom_pt=plan.target_bottom_pt,
        anchor_mode=original.anchor_mode,
        anchor_x=original.anchor_x,
        segments=tuple(plan.segments),
        reject_reasons=tuple(reject_reasons),
    )

    return FitResult(
        font_size=plan.final_size_pt or max(1.0, original.orig_ink_height_pt),
        scale_x=scale_x or 1.0,
        method="visual_fit" if safe else "unsafe",
        target_advance=plan.unscaled_advance_pt,
        segments=segments,
        segment_sizes=[segment.size_pt for segment in plan.segments],
        visual_decision=decision,
        unsafe_reason="; ".join(reject_reasons),
    )


@dataclass(frozen=True)
class _Plan:
    segments: tuple[SegmentFitPlan, ...]
    unscaled_advance_pt: float
    target_top_pt: float | None
    target_bottom_pt: float | None
    metric_used: VisualMetricKind | None
    original_metric_pt: float | None
    target_metric_du: float | None
    raw_size_pt: float | None
    final_size_pt: float | None
    reject_reasons: tuple[str, ...]


def _build_segment_plans(
    line: TextLine,
    segments: list[FontSegment],
    visual_profiles: dict[str, FontVisualProfile],
    original: OriginalLineVisual,
    role: LineRole,
) -> _Plan:
    reject_reasons: list[str] = []
    plans: list[SegmentFitPlan] = []
    x_offset = 0.0
    target_top = 0.0
    target_bottom = 0.0

    metric_used, original_metric, target_metric = _choose_metric(line, segments, visual_profiles, original, role)
    if original_metric is None or original_metric <= 0:
        reject_reasons.append("missing original visual metric")
    if target_metric is None or target_metric <= 0:
        reject_reasons.append("missing target visual metric")

    raw_size = None
    if original_metric and target_metric:
        primary_profile = _profile_for_segment(segments[0], visual_profiles)
        raw_size = original_metric * primary_profile.upem / target_metric
        if raw_size < 1 or raw_size > 200:
            reject_reasons.append(f"implausible visual font size ({raw_size:.2f}pt)")

    if reject_reasons or raw_size is None:
        return _Plan((), 0.0, None, None, metric_used, original_metric, target_metric, raw_size, raw_size, tuple(reject_reasons))

    for segment in segments:
        profile = _profile_for_segment(segment, visual_profiles)
        segment_size = _segment_size(line, segment, profile, original, role, raw_size)
        script = _hb_script(segment.script)
        measure = measure_profile_text_du(segment.text, profile, script)
        if measure.has_notdef:
            reject_reasons.append("target shaping produced .notdef glyph")
        advance_pt = measure.advance_du * segment_size / profile.upem
        top_pt = measure.ink_y_max_du * segment_size / profile.upem
        bottom_pt = -measure.ink_y_min_du * segment_size / profile.upem
        target_top = max(target_top, top_pt)
        target_bottom = max(target_bottom, bottom_pt)
        plans.append(
            SegmentFitPlan(
                text=segment.text,
                font=segment.font,
                script=segment.script,
                size_pt=segment_size,
                unscaled_advance_pt=advance_pt,
                x_offset_unscaled_pt=x_offset,
            )
        )
        x_offset += advance_pt

    if role == LineRole.MIXED_LATIN_CJK and plans:
        # Whitespace-only segments carry no ink, so their size cannot create
        # a visible jump; lone spaces at script boundaries inherit the
        # neighboring fallback font and would otherwise trip this gate.
        sizes = [plan.size_pt for plan in plans if plan.text.strip()]
        # Within one line, per-script sizes more than ~8% apart read as a
        # visible size jump between Latin and CJK segments.
        if sizes and min(sizes) > 0 and max(sizes) / min(sizes) > 1.08:
            reject_reasons.append("mixed fallback segment sizes diverge too far")

    return _Plan(
        segments=tuple(plans),
        unscaled_advance_pt=sum(plan.unscaled_advance_pt for plan in plans),
        target_top_pt=target_top,
        target_bottom_pt=target_bottom,
        metric_used=metric_used,
        original_metric_pt=original_metric,
        target_metric_du=target_metric,
        raw_size_pt=raw_size,
        final_size_pt=raw_size,
        reject_reasons=tuple(reject_reasons),
    )


def _rescale_plan(plan: _Plan, factor: float, visual_profiles: dict[str, FontVisualProfile]) -> _Plan:
    plans: list[SegmentFitPlan] = []
    x_offset = 0.0
    target_top = 0.0
    target_bottom = 0.0

    for segment in plan.segments:
        profile = visual_profiles[str(segment.font.path)]
        size = segment.size_pt * factor
        measure = measure_profile_text_du(segment.text, profile, _hb_script(segment.script))
        advance_pt = measure.advance_du * size / profile.upem
        top_pt = measure.ink_y_max_du * size / profile.upem
        bottom_pt = -measure.ink_y_min_du * size / profile.upem
        target_top = max(target_top, top_pt)
        target_bottom = max(target_bottom, bottom_pt)
        plans.append(
            SegmentFitPlan(
                text=segment.text,
                font=segment.font,
                script=segment.script,
                size_pt=size,
                unscaled_advance_pt=advance_pt,
                x_offset_unscaled_pt=x_offset,
            )
        )
        x_offset += advance_pt

    return _Plan(
        segments=tuple(plans),
        unscaled_advance_pt=sum(segment.unscaled_advance_pt for segment in plans),
        target_top_pt=target_top,
        target_bottom_pt=target_bottom,
        metric_used=plan.metric_used,
        original_metric_pt=plan.original_metric_pt,
        target_metric_du=plan.target_metric_du,
        raw_size_pt=plan.raw_size_pt,
        final_size_pt=(plan.final_size_pt * factor) if plan.final_size_pt else None,
        reject_reasons=plan.reject_reasons,
    )


def _choose_metric(
    line: TextLine,
    segments: list[FontSegment],
    visual_profiles: dict[str, FontVisualProfile],
    original: OriginalLineVisual,
    role: LineRole,
) -> tuple[VisualMetricKind, float | None, float | None]:
    primary_profile = _profile_for_segment(segments[0], visual_profiles)
    stats = original.char_stats
    source_size = _line_font_size(line)

    if role == LineRole.PAGE_NUMBER:
        original_metric = _original_metric(VisualMetricKind.DIGIT_HEIGHT, stats.digit_height_pt, source_size, 0.68, stats.measured_ink)
        return (VisualMetricKind.DIGIT_HEIGHT, original_metric, primary_profile.digit_ink_height or primary_profile.digit_height)
    if role == LineRole.CJK_BODY:
        original_metric = _original_metric(VisualMetricKind.IDEOGRAPHIC_HEIGHT, stats.cjk_height_pt, source_size, CJK_INK_RATIO, stats.measured_ink)
        return (
            VisualMetricKind.IDEOGRAPHIC_HEIGHT,
            original_metric,
            _ideographic_height(primary_profile),
        )
    if role == LineRole.MIXED_LATIN_CJK:
        if primary_profile.x_ink_height or primary_profile.x_height:
            original_metric = _original_metric(VisualMetricKind.X_HEIGHT, stats.lower_mid_height_pt, source_size, 0.50, stats.measured_ink)
            return (VisualMetricKind.X_HEIGHT, original_metric, primary_profile.x_ink_height or primary_profile.x_height)
        original_metric = _original_metric(VisualMetricKind.ACTUAL_LINE_INK, None, source_size, 0.75)
        return (VisualMetricKind.ACTUAL_LINE_INK, original_metric, _actual_line_ink_du(line.text, primary_profile, segments[0].script))
    if role == LineRole.HEADING and _upper_ratio(line.text) >= 0.70:
        original_metric = _original_metric(VisualMetricKind.CAP_HEIGHT, stats.cap_height_pt, source_size, 0.70, stats.measured_ink)
        return (VisualMetricKind.CAP_HEIGHT, original_metric, primary_profile.cap_ink_height or primary_profile.cap_height)
    if role == LineRole.HEADING:
        original_metric = _original_metric(VisualMetricKind.ACTUAL_LINE_INK, None, source_size, 0.75)
        return (VisualMetricKind.ACTUAL_LINE_INK, original_metric, _actual_line_ink_du(line.text, primary_profile, segments[0].script))

    if primary_profile.x_ink_height or primary_profile.x_height:
        original_metric = _original_metric(VisualMetricKind.X_HEIGHT, stats.lower_mid_height_pt, source_size, 0.50, stats.measured_ink)
        return (VisualMetricKind.X_HEIGHT, original_metric, primary_profile.x_ink_height or primary_profile.x_height)
    original_metric = _original_metric(VisualMetricKind.ACTUAL_LINE_INK, None, source_size, 0.75)
    return (VisualMetricKind.ACTUAL_LINE_INK, original_metric, _actual_line_ink_du(line.text, primary_profile, segments[0].script))


def _segment_size(
    line: TextLine,
    segment: FontSegment,
    profile: FontVisualProfile,
    original: OriginalLineVisual,
    role: LineRole,
    default_size: float,
) -> float:
    stats = original.char_stats
    if role in {LineRole.CJK_BODY, LineRole.MIXED_LATIN_CJK} and segment.script == "cjk":
        ideo_height = _ideographic_height(profile)
        if ideo_height and (stats.cjk_height_pt or stats.nonspace_height_pt):
            source_metric = _original_metric(VisualMetricKind.IDEOGRAPHIC_HEIGHT, stats.cjk_height_pt, _line_font_size(line), CJK_INK_RATIO, stats.measured_ink)
            return source_metric * profile.upem / ideo_height
    if role == LineRole.MIXED_LATIN_CJK and segment.script != "cjk" and stats.lower_mid_height_pt and (profile.x_ink_height or profile.x_height):
        source_metric = _original_metric(VisualMetricKind.X_HEIGHT, stats.lower_mid_height_pt, _line_font_size(line), 0.50, stats.measured_ink)
        return source_metric * profile.upem / (profile.x_ink_height or profile.x_height)
    return default_size


def _actual_line_ink_du(text: str, profile: FontVisualProfile, script: str) -> float | None:
    measure = measure_profile_text_du(text, profile, _hb_script(script))
    height = measure.ink_y_max_du - measure.ink_y_min_du
    return height if height > 0 else None


def _profile_for_segment(segment: FontSegment, profiles: dict[str, FontVisualProfile]) -> FontVisualProfile:
    return profiles[str(segment.font.path)]


def _char_visual_stats(
    chars: list[CharGeometry],
    line: TextLine,
    sampler: "PageInkSampler | None" = None,
) -> CharVisualStats:
    lower_heights: list[float] = []
    cap_heights: list[float] = []
    digit_heights: list[float] = []
    cjk_heights: list[float] = []
    nonspace_heights: list[float] = []

    sampler_hits = 0
    for char in chars:
        if not char.char.strip():
            continue
        height = None
        if sampler is not None:
            height = sampler.char_ink_height_pt(char)
            if height is not None:
                sampler_hits += 1
        if height is None:
            height = max(0.0, char.bbox[3] - char.bbox[1])
        nonspace_heights.append(height)
        value = char.char
        if value in "acemnorsuvwxz":
            lower_heights.append(height)
        elif value.isupper():
            cap_heights.append(height)
        elif value.isdigit():
            digit_heights.append(height)
        elif is_cjk_codepoint(ord(value)):
            cjk_heights.append(height)

    fallback_height = max(0.0, line.bbox[3] - line.bbox[1])
    nonspace_height = _median_or_none(nonspace_heights) or fallback_height
    measured_ink = bool(nonspace_heights) and sampler_hits >= max(3, len(nonspace_heights) // 2)
    return CharVisualStats(
        measured_ink=measured_ink,
        lower_mid_count=len(lower_heights),
        lower_mid_height_pt=_median_or_none(lower_heights),
        cap_count=len(cap_heights),
        cap_height_pt=_median_or_none(cap_heights),
        digit_count=len(digit_heights),
        digit_height_pt=_median_or_none(digit_heights),
        cjk_count=len(cjk_heights),
        cjk_height_pt=_median_or_none(cjk_heights),
        nonspace_count=len(nonspace_heights),
        nonspace_height_pt=nonspace_height,
    )


def _line_chars(line: TextLine) -> list[CharGeometry]:
    chars: list[CharGeometry] = []
    for run in line.runs:
        chars.extend(run.chars)
    return chars


def _line_font_size(line: TextLine) -> float:
    sizes = [run.font_size for run in line.runs if run.font_size > 0]
    return float(median(sizes)) if sizes else max(1.0, line.bbox[3] - line.bbox[1])


# Plausible ratios of each perceptual metric to the nominal font size.
# PyMuPDF texttrace/rawdict char bboxes are usually font boxes (height ==
# font size for every char), not glyph ink; observed values outside the
# window for their metric kind are treated as box artifacts and replaced by
# the role/source-size estimate. Real x-heights live around 0.42-0.56 of the
# size, caps/digits around 0.60-0.75, CJK ideographs around 0.85-0.95.
_METRIC_PLAUSIBLE_WINDOWS: dict[VisualMetricKind, tuple[float, float]] = {
    VisualMetricKind.X_HEIGHT: (0.35, 0.60),
    VisualMetricKind.CAP_HEIGHT: (0.55, 0.80),
    VisualMetricKind.DIGIT_HEIGHT: (0.55, 0.80),
    # Upper bound deliberately < 1.0: PyMuPDF font-box char heights equal the
    # font size exactly, and real ideograph ink stays below ~0.95 em.
    VisualMetricKind.IDEOGRAPHIC_HEIGHT: (0.75, 0.97),
    VisualMetricKind.ACTUAL_LINE_INK: (0.55, 1.05),
}

# Wider windows for ink-sampled measurements. Real painted ink is trusted
# further because the nominal PDF font size itself can be off (CID font
# matrices), but values at/above the font-box signature (~1.0x size for
# Latin classes) still read as background contamination and are rejected.
_MEASURED_PLAUSIBLE_WINDOWS: dict[VisualMetricKind, tuple[float, float]] = {
    VisualMetricKind.X_HEIGHT: (0.30, 0.75),
    VisualMetricKind.CAP_HEIGHT: (0.45, 0.95),
    VisualMetricKind.DIGIT_HEIGHT: (0.45, 0.95),
    VisualMetricKind.IDEOGRAPHIC_HEIGHT: (0.65, 0.98),
    VisualMetricKind.ACTUAL_LINE_INK: (0.55, 1.25),
}


def _original_metric(
    kind: VisualMetricKind,
    observed_metric: float | None,
    source_size: float,
    ratio: float,
    trusted: bool = False,
) -> float:
    estimated = source_size * ratio
    if observed_metric is None or observed_metric <= 0 or source_size <= 0:
        return estimated
    windows = _MEASURED_PLAUSIBLE_WINDOWS if trusted else _METRIC_PLAUSIBLE_WINDOWS
    low, high = windows[kind]
    if not source_size * low <= observed_metric <= source_size * high:
        return estimated
    return observed_metric


def _anchor_mode(line: TextLine, page_rect: fitz.Rect) -> AnchorMode:
    text = line.text.strip()
    visible_count = sum(1 for char in text if not char.isspace())
    width = max(0.0, line.bbox[2] - line.bbox[0])
    center_x = (line.bbox[0] + line.bbox[2]) / 2
    if visible_count <= 12 and width <= page_rect.width * 0.18 and abs(center_x - page_rect.width / 2) <= page_rect.width * 0.12:
        return AnchorMode.CENTER
    if line.bbox[2] > page_rect.width * 0.82 and width <= page_rect.width * 0.25:
        return AnchorMode.RIGHT
    return AnchorMode.LEFT


def _anchor_x(line: TextLine, mode: AnchorMode) -> float:
    if mode == AnchorMode.CENTER:
        return (line.bbox[0] + line.bbox[2]) / 2
    if mode == AnchorMode.RIGHT:
        return line.bbox[2]
    return min((run.origin[0] for run in line.runs), default=line.bbox[0])


def _role_scale_limits(role: LineRole, thresholds: VisualFitThresholds) -> tuple[float, float]:
    return {
        LineRole.BODY: thresholds.body_scale,
        LineRole.HEADING: thresholds.heading_scale,
        LineRole.RUNNING_HEADER: thresholds.running_header_scale,
        LineRole.PAGE_NUMBER: thresholds.page_number_scale,
        LineRole.FOOTNOTE: thresholds.footnote_scale,
        LineRole.CAPTION: thresholds.caption_scale,
        LineRole.CJK_BODY: thresholds.cjk_scale,
        LineRole.MIXED_LATIN_CJK: thresholds.mixed_scale,
        LineRole.UNKNOWN: thresholds.body_scale,
    }[role]


def _ideographic_height(profile: FontVisualProfile) -> float | None:
    if profile.ideographic_top is None or profile.ideographic_bottom is None:
        return None
    height = profile.ideographic_top - profile.ideographic_bottom
    return float(height) if height > 0 else None


def _upper_ratio(text: str) -> float:
    alpha = [char for char in text if char.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for char in alpha if char.isupper()) / len(alpha)


def _hb_script(script: str) -> str:
    return "Hani" if script == "cjk" else "Latn"


def _union_rects(rects: list[RectTuple]) -> RectTuple:
    x0, y0, x1, y1 = rects[0]
    for rect in rects[1:]:
        x0 = min(x0, rect[0])
        y0 = min(y0, rect[1])
        x1 = max(x1, rect[2])
        y1 = max(y1, rect[3])
    return (x0, y0, x1, y1)


def _median_or_none(values: list[float]) -> float | None:
    return float(median(values)) if values else None
