from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from pathlib import Path
from statistics import median
from typing import Any

import fitz

from .classifier import classify_page
from .extractor import extract_page_index
from .font_utils import build_font_chain
from .inserter import rgb_from_pymupdf
from .models import LineRole, PageIndex, TextLine
from .safety import analyze_page_safety
from .shaper import shape_line


PLANNER_VERSION = "live-plan-v3"
LIVE_FALLBACK_MIN_SCALE_X = 0.94
LIVE_FALLBACK_MAX_SCALE_X = 1.08
LIVE_CALIBRATED_MIN_SCALE_X = 0.96
LIVE_CALIBRATED_MAX_SCALE_X = 1.04
LIVE_CALIBRATION_MIN_LINES = 5
LIVE_CALIBRATION_MIN_EVIDENCE = 3.0
LIVE_CALIBRATION_MIN_FACTOR = 0.78
LIVE_CALIBRATION_MAX_FACTOR = 1.34
LIVE_CALIBRATION_ACTIVATE_LOW = 0.91
LIVE_CALIBRATION_ACTIVATE_HIGH = 1.10
LIVE_CALIBRATION_MAX_DISPERSION = 0.085
LIVE_CALIBRATION_MAX_TAIL = 0.155


@dataclass(frozen=True)
class LivePlanOptions:
    input_pdf: Path
    target_font: Path
    page_index: int
    cjk_fallback: Path | None = None
    mode: str = "conservative"


@dataclass(frozen=True)
class LiveLineCalibration:
    region_id: str
    factor: float
    residual_scale_x: float
    draw_scale_x: float
    line_count: int
    evidence: float
    dispersion: float
    tail: float
    fallback_fraction: float


@dataclass(frozen=True)
class _CalibrationCandidate:
    line: TextLine
    raw_scale_x: float
    width: float
    width_ratio: float
    visible_count: int
    fallback: bool
    weight: float


def build_live_page_plan(options: LivePlanOptions) -> dict[str, Any]:
    font_chain = build_font_chain(options.target_font, options.cjk_fallback)
    doc = fitz.open(options.input_pdf)
    try:
        if options.page_index < 0 or options.page_index >= doc.page_count:
            return _error_plan(options.page_index, f"page_index out of range: {options.page_index}")

        page = doc[options.page_index]
        classification = classify_page(page)
        page_index = extract_page_index(page, options.page_index, classification)
        analyze_page_safety(page, page_index, font_chain, options.mode)
        return _plan_from_page(page, page_index)
    finally:
        doc.close()


def _plan_from_page(page: fitz.Page, page_index: PageIndex) -> dict[str, Any]:
    safe_lines = [
        line
        for line in page_index.lines
        if line.safety == "safe" and line.fit_result and line.fit_result.safe
    ]
    safe_line_ids = {id(line) for line in safe_lines}
    fallback_lines = [
        line
        for line in page_index.lines
        if id(line) not in safe_line_ids and _live_fallback_eligible(line)
    ]
    fallback_line_ids = {id(line) for line in fallback_lines}
    live_lines = safe_lines + fallback_lines
    calibrations = _build_live_calibrations(page_index, live_lines, safe_line_ids)
    unsafe_lines = [
        line
        for line in page_index.lines
        if line.safety == "unsafe" and id(line) not in fallback_line_ids
    ]

    if page_index.classification not in {"native", "hybrid"}:
        status = "original"
    elif live_lines and unsafe_lines:
        status = "partial"
    elif live_lines:
        status = "full"
    else:
        status = "original"

    safe_regions = []
    draw_runs = []
    for line_index, line in enumerate(live_lines):
        region_id = f"p{page_index.page_no + 1}-l{line_index + 1}"
        planner_safety = "export-safe" if id(line) in safe_line_ids else "live-fallback"
        safe_regions.append(
            {
                "id": region_id,
                "bboxPdf": _rect(line.bbox),
                "erasePaddingPxAt1x": 2,
                "expectedText": line.text,
                "plannerSafety": planner_safety,
                "reason": "" if planner_safety == "export-safe" else "; ".join(line.unsafe_reasons),
            }
        )
        draw_runs.extend(_draw_runs_for_line(line, region_id, planner_safety, calibrations.get(id(line))))

    return {
        "pageIndex": page_index.page_no,
        "status": status,
        "classification": page_index.classification,
        "pageBox": _rect(tuple(page.rect)),
        "rotation": int(page.rotation),
        "safeRegions": safe_regions,
        "drawRuns": draw_runs,
        "unsafeRegions": [
            {
                "bboxPdf": _rect(line.bbox),
                "reason": "; ".join(line.unsafe_reasons) or "unsafe",
                "text": line.text,
            }
            for line in unsafe_lines
        ],
        "plannerVersion": PLANNER_VERSION,
    }


def _live_fallback_eligible(line: TextLine) -> bool:
    fit = line.fit_result
    decision = fit.visual_decision if fit else None
    if not fit or not decision or not fit.segments:
        return False
    if line.direction != "ltr" or not line.text.strip():
        return False
    if fit.scale_x <= 0 or fit.font_size <= 0:
        return False
    return all(_live_overridable_reason(reason) for reason in line.unsafe_reasons)


def _live_overridable_reason(reason: str) -> bool:
    return (
        reason.startswith("region coherence rejected")
        or reason.startswith("replacement text does not fit visual geometry")
        or reason.startswith("visual scale outside")
        or reason.startswith("low visual role confidence")
        or reason.startswith("unknown visual line role")
        or reason.startswith("target ink overflows")
    )


def _draw_runs_for_line(
    line: TextLine,
    region_id: str,
    planner_safety: str,
    calibration: LiveLineCalibration | None = None,
) -> list[dict[str, Any]]:
    fit = line.fit_result
    if not fit or not fit.visual_decision:
        return []

    color = _rgba(line.runs[0].color if line.runs else 0)
    draw_scale_x = _draw_scale_x(fit.scale_x, planner_safety, calibration)
    size_multiplier = _font_size_multiplier(fit.scale_x, draw_scale_x, calibration)
    cursor_x = _line_origin_x(line, draw_scale_x, size_multiplier)
    baseline_y = line.baseline_y
    decision = fit.visual_decision
    confidence = float(decision.confidence) if decision else 0.0
    method = fit.method
    if calibration:
        method = "live_region_calibrated"
    elif planner_safety == "live-fallback":
        method = (
            "live_fallback_distortion_capped"
            if abs(draw_scale_x - fit.scale_x) > 0.001 or abs(size_multiplier - 1.0) > 0.001
            else "live_fallback"
        )
    runs = []

    for index, segment in enumerate(fit.segments):
        base_font_size = fit.segment_sizes[index] if index < len(fit.segment_sizes) else fit.font_size
        font_size = base_font_size * size_multiplier
        run_id = f"{region_id}-r{index + 1}"
        runs.append(
            {
                "id": run_id,
                "regionId": region_id,
                "text": segment.text,
                "matrixPdf": [1.0, 0.0, 0.0, 1.0, cursor_x, baseline_y],
                "fontSize": float(font_size),
                "scaleX": float(draw_scale_x),
                "color": color,
                "direction": line.direction,
                "script": segment.script,
                "fontRole": segment.font.label,
                "fontPath": str(segment.font.path),
                "fit": {
                    "method": method,
                    "confidence": confidence,
                    "plannerSafety": planner_safety,
                    "rawScaleX": float(fit.scale_x),
                    "fontSizeMultiplier": float(size_multiplier),
                    **_calibration_fit_payload(calibration),
                },
            }
        )
        cursor_x += shape_line(segment.text, segment.font, font_size).advance * draw_scale_x

    return runs


def _draw_scale_x(
    raw_scale_x: float,
    planner_safety: str,
    calibration: LiveLineCalibration | None = None,
) -> float:
    if calibration:
        return calibration.draw_scale_x
    if planner_safety == "export-safe":
        return raw_scale_x
    return min(LIVE_FALLBACK_MAX_SCALE_X, max(LIVE_FALLBACK_MIN_SCALE_X, raw_scale_x))


def _font_size_multiplier(
    raw_scale_x: float,
    draw_scale_x: float,
    calibration: LiveLineCalibration | None = None,
) -> float:
    if calibration:
        return calibration.factor
    if raw_scale_x >= LIVE_FALLBACK_MIN_SCALE_X:
        return 1.0
    return max(0.72, raw_scale_x / max(draw_scale_x, 0.01))


def _build_live_calibrations(
    page_index: PageIndex,
    live_lines: list[TextLine],
    safe_line_ids: set[int],
) -> dict[int, LiveLineCalibration]:
    candidates = [_calibration_candidate(page_index, line, safe_line_ids) for line in live_lines]
    body_candidates = [candidate for candidate in candidates if candidate]
    if len(body_candidates) < LIVE_CALIBRATION_MIN_LINES:
        return {}

    calibrations: dict[int, LiveLineCalibration] = {}
    for region_no, region in enumerate(_candidate_regions(page_index, body_candidates), start=1):
        region_calibrations = _region_calibrations(f"body-{region_no}", region)
        calibrations.update(region_calibrations)
    return calibrations


def _calibration_candidate(
    page_index: PageIndex,
    line: TextLine,
    safe_line_ids: set[int],
) -> _CalibrationCandidate | None:
    fit = line.fit_result
    decision = fit.visual_decision if fit else None
    if not fit or not decision or decision.role != LineRole.BODY:
        return None
    if line.direction != "ltr" or not line.text.strip() or fit.scale_x <= 0 or fit.target_advance <= 0:
        return None

    width = max(0.0, line.bbox[2] - line.bbox[0])
    width_ratio = width / max(float(page_index.width_pt), 1.0)
    if width_ratio < 0.24 or width_ratio > 0.82:
        return None

    visible_count = sum(1 for char in line.text if not char.isspace())
    if visible_count < 18:
        return None

    # Very short final paragraph lines do not constrain the page text system
    # well, so they should not pull the calibration factor around.
    char_weight = min(1.0, max(0.25, (visible_count / 65) ** 0.5))
    width_weight = 1.0 if width_ratio >= 0.42 else 0.55
    confidence_weight = max(0.35, float(decision.confidence))
    return _CalibrationCandidate(
        line=line,
        raw_scale_x=float(fit.scale_x),
        width=width,
        width_ratio=width_ratio,
        visible_count=visible_count,
        fallback=id(line) not in safe_line_ids,
        weight=char_weight * width_weight * confidence_weight,
    )


def _candidate_regions(
    page_index: PageIndex,
    candidates: list[_CalibrationCandidate],
) -> list[list[_CalibrationCandidate]]:
    ordered = sorted(candidates, key=lambda candidate: (candidate.line.bbox[1], candidate.line.bbox[0]))
    median_width = _median([candidate.width for candidate in ordered]) or 1.0
    baseline_gap = _body_baseline_gap(ordered)
    regions: list[list[_CalibrationCandidate]] = []
    current: list[_CalibrationCandidate] = []
    previous: _CalibrationCandidate | None = None

    for candidate in ordered:
        if previous is None:
            current = [candidate]
            previous = candidate
            continue

        if _same_body_region(page_index, previous, candidate, median_width, baseline_gap):
            current.append(candidate)
        else:
            if current:
                regions.append(current)
            current = [candidate]
        previous = candidate

    if current:
        regions.append(current)
    return regions


def _same_body_region(
    page_index: PageIndex,
    previous: _CalibrationCandidate,
    candidate: _CalibrationCandidate,
    median_width: float,
    baseline_gap: float,
) -> bool:
    gap = candidate.line.baseline_y - previous.line.baseline_y
    if baseline_gap <= 0 or gap <= 0:
        return False
    gap_ratio = gap / baseline_gap
    if not 0.55 <= gap_ratio <= 1.75:
        return False

    left_delta = abs(candidate.line.bbox[0] - previous.line.bbox[0])
    body_indent = max(10.0, float(page_index.width_pt) * 0.03)
    indent_delta = abs(left_delta - body_indent)
    x_continuity = left_delta <= 7.0 or indent_delta <= 10.0
    if not x_continuity:
        return False

    min_width_ratio = min(previous.width, candidate.width) / max(median_width, 1.0)
    return min_width_ratio >= 0.42


def _region_calibrations(
    region_id: str,
    region: list[_CalibrationCandidate],
) -> dict[int, LiveLineCalibration]:
    working_region = region
    if len(working_region) < LIVE_CALIBRATION_MIN_LINES:
        return {}

    weights = [candidate.weight for candidate in working_region]
    evidence = sum(weights)
    if evidence < LIVE_CALIBRATION_MIN_EVIDENCE:
        return {}

    z_values = [log(max(0.01, candidate.raw_scale_x)) for candidate in working_region]
    z_region = _weighted_quantile(z_values, weights, 0.5)
    factor = exp(z_region)
    if not LIVE_CALIBRATION_MIN_FACTOR <= factor <= LIVE_CALIBRATION_MAX_FACTOR:
        return {}

    residuals = [abs(z_value - z_region) for z_value in z_values]
    dispersion = _weighted_quantile(residuals, weights, 0.5)
    tail = _weighted_quantile(residuals, weights, 0.90)
    if dispersion > LIVE_CALIBRATION_MAX_DISPERSION:
        return {}
    if tail > LIVE_CALIBRATION_MAX_TAIL:
        working_region = [
            candidate
            for candidate, residual in zip(working_region, residuals)
            if residual <= LIVE_CALIBRATION_MAX_TAIL
        ]
        if len(working_region) < LIVE_CALIBRATION_MIN_LINES:
            return {}
        weights = [candidate.weight for candidate in working_region]
        evidence = sum(weights)
        if evidence < LIVE_CALIBRATION_MIN_EVIDENCE:
            return {}
        z_values = [log(max(0.01, candidate.raw_scale_x)) for candidate in working_region]
        z_region = _weighted_quantile(z_values, weights, 0.5)
        factor = exp(z_region)
        if not LIVE_CALIBRATION_MIN_FACTOR <= factor <= LIVE_CALIBRATION_MAX_FACTOR:
            return {}
        residuals = [abs(z_value - z_region) for z_value in z_values]
        dispersion = _weighted_quantile(residuals, weights, 0.5)
        tail = _weighted_quantile(residuals, weights, 0.90)
        if dispersion > LIVE_CALIBRATION_MAX_DISPERSION or tail > LIVE_CALIBRATION_MAX_TAIL:
            return {}

    fallback_fraction = sum(candidate.weight for candidate in working_region if candidate.fallback) / max(evidence, 0.01)
    scale_error = factor < LIVE_CALIBRATION_ACTIVATE_LOW or factor > LIVE_CALIBRATION_ACTIVATE_HIGH
    if fallback_fraction < 0.35 and not scale_error:
        return {}

    calibrations: dict[int, LiveLineCalibration] = {}
    for candidate in working_region:
        residual_scale_x = candidate.raw_scale_x / max(factor, 0.01)
        draw_scale_x = min(
            LIVE_CALIBRATED_MAX_SCALE_X,
            max(LIVE_CALIBRATED_MIN_SCALE_X, residual_scale_x),
        )
        calibrations[id(candidate.line)] = LiveLineCalibration(
            region_id=region_id,
            factor=factor,
            residual_scale_x=residual_scale_x,
            draw_scale_x=draw_scale_x,
            line_count=len(working_region),
            evidence=evidence,
            dispersion=dispersion,
            tail=tail,
            fallback_fraction=fallback_fraction,
        )
    return calibrations


def _body_baseline_gap(candidates: list[_CalibrationCandidate]) -> float:
    baselines = sorted(candidate.line.baseline_y for candidate in candidates)
    gaps = [b - a for a, b in zip(baselines, baselines[1:]) if 4 <= b - a <= 30]
    return _median(gaps) or 12.0


def _calibration_fit_payload(calibration: LiveLineCalibration | None) -> dict[str, float | int | str]:
    if not calibration:
        return {}
    return {
        "calibration": calibration.region_id,
        "calibrationFactor": float(calibration.factor),
        "residualScaleX": float(calibration.residual_scale_x),
        "calibrationLines": calibration.line_count,
        "calibrationEvidence": round(calibration.evidence, 4),
        "calibrationDispersion": round(calibration.dispersion, 5),
        "calibrationTail": round(calibration.tail, 5),
        "calibrationFallbackFraction": round(calibration.fallback_fraction, 4),
    }


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _weighted_quantile(values: list[float], weights: list[float], quantile: float) -> float:
    pairs = sorted(zip(values, weights), key=lambda pair: pair[0])
    total = sum(max(0.0, weight) for _, weight in pairs)
    if total <= 0:
        return _median(values) or 0.0
    threshold = total * quantile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += max(0.0, weight)
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _line_origin_x(line: TextLine, scale_x: float, size_multiplier: float) -> float:
    fit = line.fit_result
    decision = fit.visual_decision if fit else None
    if not fit or not decision:
        return min((run.origin[0] for run in line.runs), default=line.bbox[0])

    scaled_advance = fit.target_advance * size_multiplier * scale_x
    if decision.anchor_mode.value == "center":
        return decision.anchor_x - scaled_advance / 2
    if decision.anchor_mode.value == "right":
        return decision.anchor_x - scaled_advance
    return decision.anchor_x


def _rgba(value: object) -> list[float]:
    red, green, blue = rgb_from_pymupdf(value)
    return [round(red * 255), round(green * 255), round(blue * 255), 1.0]


def _rect(value: tuple[float, float, float, float]) -> list[float]:
    return [float(value[0]), float(value[1]), float(value[2]), float(value[3])]


def _error_plan(page_index: int, message: str) -> dict[str, Any]:
    return {
        "pageIndex": page_index,
        "status": "error",
        "classification": "unknown",
        "pageBox": [0.0, 0.0, 0.0, 0.0],
        "rotation": 0,
        "safeRegions": [],
        "drawRuns": [],
        "unsafeRegions": [],
        "plannerVersion": PLANNER_VERSION,
        "error": message,
    }
