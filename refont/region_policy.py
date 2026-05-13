from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from statistics import median

import fitz

from .models import LineRole, PageIndex, TextLine
from .visual_fit import PageVisualStats


@dataclass(frozen=True)
class RegionCaps:
    system_cap: float
    dispersion_cap: float
    tail_cap: float
    local_abs_cap: float
    min_evidence: float
    min_lines: int
    hard_edge: float


@dataclass
class RegionLine:
    line: TextLine
    z: float
    weight_fit: float
    weight_visual: float
    width_ratio: float
    anchor_kind: str


def apply_region_coherence_policy(
    page_index: PageIndex,
    page_rect: fitz.Rect,
    page_stats: PageVisualStats,
    mode: str,
) -> None:
    """Use body-region coherence to avoid mixed target/original paragraphs.

    This pass treats per-line visual fit as evidence. It can override a
    scale-only visual rejection when a connected body region is coherent, and
    it can skip a locally safe body region when the region as a whole is not
    coherent enough.
    """

    caps = _caps_for(mode, page_index.classification)
    region_id = 0
    decisions: list[dict] = []

    for region in _body_regions(page_index.lines, page_rect, page_stats):
        if len(region) < caps.min_lines:
            continue

        region_id += 1
        score = _score_region(region, caps)
        decision = {
            "region_id": region_id,
            "role": "body",
            "line_count": len(region),
            "decision": "convert" if score["accept"] else "skip",
            **{key: value for key, value in score.items() if key != "accept"},
        }
        decisions.append(decision)

        if score["accept"]:
            _accept_region(region, score)
        else:
            _skip_region(region, score)

    page_index.region_decisions = decisions


def _body_regions(lines: list[TextLine], page_rect: fitz.Rect, page_stats: PageVisualStats) -> list[list[RegionLine]]:
    ordered = sorted(
        [line for line in lines if _has_body_observation(line)],
        key=lambda line: (line.bbox[1], line.bbox[0]),
    )
    if not ordered:
        return []

    regions: list[list[RegionLine]] = []
    current: list[RegionLine] = []
    previous_line: TextLine | None = None
    median_width = _median_width(ordered)

    for line in ordered:
        if previous_line is None:
            current = [_region_line(line, median_width)]
            previous_line = line
            continue

        q = _continuity_weight(previous_line, line, page_rect, page_stats, median_width)
        if q >= 0.75:
            current.append(_region_line(line, median_width))
        else:
            if current:
                regions.append(current)
            current = [_region_line(line, median_width)]
        previous_line = line

    if current:
        regions.append(current)
    return regions


def _score_region(region: list[RegionLine], caps: RegionCaps) -> dict:
    hard_failures = [item for item in region if not _region_convertible(item.line)]
    if hard_failures:
        return {
            "accept": False,
            "reason": "region contains non-overridable line failures",
            "hard_failures": len(hard_failures),
        }

    evidence = sum(item.weight_fit for item in region)
    if evidence < caps.min_evidence:
        return {
            "accept": False,
            "reason": "insufficient region fit evidence",
            "evidence": round(evidence, 3),
        }

    z_values = [item.z for item in region]
    weights = [item.weight_fit for item in region]
    z_region = _weighted_median(z_values, weights)
    residuals = [abs(item.z - z_region) for item in region]
    abs_values = [abs(item.z) for item in region]
    dispersion = _weighted_median(residuals, weights)
    tail = _weighted_quantile(residuals, weights, 0.90)
    local_tail_abs = _weighted_quantile(abs_values, weights, 0.95)
    max_abs = max(abs_values)

    failures: list[str] = []
    if abs(z_region) > caps.system_cap:
        failures.append("regional scale too large")
    if dispersion > caps.dispersion_cap:
        failures.append("regional scale dispersion too large")
    if tail > caps.tail_cap:
        failures.append("regional scale outlier tail too large")
    if local_tail_abs > caps.local_abs_cap:
        failures.append("applied line scale too large")

    return {
        "accept": not failures,
        "reason": "; ".join(failures) if failures else "",
        "scale_region": round(exp(z_region), 4),
        "z_region": round(z_region, 5),
        "dispersion": round(dispersion, 5),
        "tail": round(tail, 5),
        "local_tail_abs": round(local_tail_abs, 5),
        "max_abs": round(max_abs, 5),
        "evidence": round(evidence, 3),
        "safe_before": sum(1 for item in region if item.line.safety == "safe"),
        "unsafe_before": sum(1 for item in region if item.line.safety == "unsafe"),
    }


def _accept_region(region: list[RegionLine], score: dict) -> None:
    for item in region:
        line = item.line
        if not line.fit_result:
            continue
        line.fit_result.method = "visual_fit_region"
        line.safety = "safe"
        line.unsafe_reasons = []


def _skip_region(region: list[RegionLine], score: dict) -> None:
    if all(item.line.safety == "safe" for item in region):
        return

    reason = "region coherence rejected"
    if score.get("reason"):
        reason = f"{reason}: {score['reason']}"
    for item in region:
        line = item.line
        if _region_convertible(line) or line.safety == "safe":
            line.safety = "unsafe"
            line.unsafe_reasons = [reason]
            if line.fit_result:
                line.fit_result.method = "unsafe"
                line.fit_result.unsafe_reason = reason


def _has_body_observation(line: TextLine) -> bool:
    decision = line.fit_result.visual_decision if line.fit_result else None
    return bool(decision and decision.role == LineRole.BODY and decision.scale_x and decision.scale_x > 0)


def _region_convertible(line: TextLine) -> bool:
    fit = line.fit_result
    decision = fit.visual_decision if fit else None
    if not fit or not decision:
        return False
    if line.safety == "safe":
        return True
    return _scale_only_rejection(decision.reject_reasons)


def _scale_only_rejection(reasons: tuple[str, ...]) -> bool:
    if not reasons:
        return True
    return all(
        reason.startswith("visual scale outside")
        or reason.startswith("replacement text does not fit visual geometry")
        for reason in reasons
    )


def _region_line(line: TextLine, median_width: float) -> RegionLine:
    decision = line.fit_result.visual_decision  # type: ignore[union-attr]
    scale = max(0.01, float(decision.scale_x or 1.0))
    visible = sum(1 for char in line.text if not char.isspace())
    width = max(0.0, line.bbox[2] - line.bbox[0])
    width_ratio = width / max(median_width, 1.0)
    char_weight = min(1.0, max(0.15, (visible / 60) ** 0.5))
    measure_weight = _measure_weight(line, width_ratio)
    confidence_weight = max(0.3, float(decision.confidence))
    return RegionLine(
        line=line,
        z=log(scale),
        weight_fit=char_weight * measure_weight * confidence_weight,
        weight_visual=char_weight * confidence_weight,
        width_ratio=width_ratio,
        anchor_kind=_anchor_kind(line, width_ratio),
    )


def _measure_weight(line: TextLine, width_ratio: float) -> float:
    text = line.text.rstrip()
    weight = 1.0
    if width_ratio >= 0.70:
        weight *= 1.0
    elif width_ratio >= 0.50:
        weight *= 0.55
    else:
        weight *= 0.25
    if text.endswith(("-", "\u00ad", "\u2010", "\u2011")):
        weight *= 1.25
    return weight


def _anchor_kind(line: TextLine, width_ratio: float) -> str:
    if width_ratio >= 0.70:
        return "two_sided"
    return "weak_left"


def _continuity_weight(
    a: TextLine,
    b: TextLine,
    page_rect: fitz.Rect,
    page_stats: PageVisualStats,
    median_width: float,
) -> float:
    baseline_gap = b.baseline_y - a.baseline_y
    expected_gap = page_stats.body_baseline_gap_pt or baseline_gap
    if expected_gap <= 0 or baseline_gap <= 0:
        return 0.0

    gap_ratio = baseline_gap / expected_gap
    if not 0.65 <= gap_ratio <= 1.55:
        return 0.0

    left_delta = abs(b.bbox[0] - a.bbox[0])
    indent_delta = abs(left_delta - _body_indent(page_rect))
    x_score = 1.0 if left_delta <= 4.0 or indent_delta <= 8.0 else 0.45

    width_a = max(0.0, a.bbox[2] - a.bbox[0])
    width_b = max(0.0, b.bbox[2] - b.bbox[0])
    min_width = min(width_a, width_b) / max(median_width, 1.0)
    width_score = 1.0 if min_width >= 0.55 else 0.65

    if _looks_like_paragraph_break(a, b, page_stats):
        x_score *= 0.35

    return max(0.0, min(1.0, x_score * width_score))


def _looks_like_paragraph_break(a: TextLine, b: TextLine, page_stats: PageVisualStats) -> bool:
    expected_gap = page_stats.body_baseline_gap_pt or 0
    if expected_gap and b.baseline_y - a.baseline_y > expected_gap * 1.35:
        return True
    if b.bbox[0] - a.bbox[0] > 14 and not a.text.rstrip().endswith(("-", "\u00ad", "\u2010", "\u2011")):
        return True
    return False


def _median_width(lines: list[TextLine]) -> float:
    widths = [max(0.0, line.bbox[2] - line.bbox[0]) for line in lines]
    return float(median(widths)) if widths else 1.0


def _body_indent(page_rect: fitz.Rect) -> float:
    return max(10.0, page_rect.width * 0.03)


def _weighted_median(values: list[float], weights: list[float]) -> float:
    return _weighted_quantile(values, weights, 0.5)


def _weighted_quantile(values: list[float], weights: list[float], quantile: float) -> float:
    pairs = sorted(zip(values, weights), key=lambda pair: pair[0])
    total = sum(max(0.0, weight) for _, weight in pairs)
    if total <= 0:
        return float(median(values)) if values else 0.0
    threshold = total * quantile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += max(0.0, weight)
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _caps_for(mode: str, classification: str) -> RegionCaps:
    if mode == "normal":
        caps = RegionCaps(
            system_cap=0.140,
            dispersion_cap=0.055,
            tail_cap=0.105,
            local_abs_cap=0.180,
            min_evidence=1.25,
            min_lines=3,
            hard_edge=0.75,
        )
    else:
        caps = RegionCaps(
            system_cap=0.125,
            dispersion_cap=0.050,
            tail_cap=0.095,
            local_abs_cap=0.165,
            min_evidence=1.50,
            min_lines=3,
            hard_edge=0.75,
        )

    # Searchable scans are more sensitive to ghosting, but do not tighten the
    # first-pass caps enough to recreate line-level mixing. A future patch
    # validator should handle the truly risky borderline cases.
    if classification == "hybrid":
        return RegionCaps(
            system_cap=caps.system_cap * 0.95,
            dispersion_cap=caps.dispersion_cap * 0.95,
            tail_cap=caps.tail_cap * 0.95,
            local_abs_cap=caps.local_abs_cap * 0.95,
            min_evidence=caps.min_evidence,
            min_lines=caps.min_lines,
            hard_edge=caps.hard_edge,
        )
    return caps
