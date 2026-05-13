from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from pathlib import Path
from statistics import median
import re
import string

import fitz

from .models import PageIndex, RectTuple, TextLayerCorrection, TextLine


RISKY_CANDIDATES: dict[str, tuple[str, ...]] = {
    "J": ("]", ")", "1", "I", "l", "/"),
    "]": ("J", ")", "1", "I", "/"),
    ")": ("]", "J", "/", "1"),
    "/": ("]", ")", "1", "I", "l"),
    "I": ("1", "l", "|", "]", "J"),
    "l": ("1", "I", "|"),
    "1": ("I", "l", "]"),
    "|": ("I", "l", "1"),
    "O": ("0",),
    "0": ("O",),
    "S": ("5",),
    "5": ("S",),
}

OPEN_TO_CLOSE = {"[": "]", "(": ")", "{": "}"}
REFERENCE_FONTS = (
    Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
    Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),
)
MIN_CORRECT_CONFIDENCE = 0.82
MIN_CORRECT_MARGIN = 0.16
MIN_VISUAL_MARGIN = 0.12
UNRESOLVED_RISK_THRESHOLD = 0.72


@dataclass(frozen=True)
class _MappedChar:
    index: int
    char: str
    bbox: RectTuple
    origin: tuple[float, float]
    font_size: float


@dataclass(frozen=True)
class _InkFeatures:
    ink_count: int
    fill_ratio: float
    bbox_width: float
    bbox_height: float
    aspect: float
    centroid_x: float
    centroid_y: float
    corr_xy: float
    verticality: float
    left_edge: float
    right_edge: float
    top_edge: float
    bottom_edge: float
    top_bar: float
    bottom_bar: float
    left_bar: float
    right_bar: float
    hook_score: float


@dataclass(frozen=True)
class _CandidateScore:
    char: str
    visual: float
    context: float
    combined: float


def validate_page_text_layer(page: fitz.Page, page_index: PageIndex, mode: str) -> None:
    """Validate and, when evidence is strong, correct searchable-scan text.

    The validator deliberately runs only for hybrid pages. Native PDFs do not
    provide an independent raster witness, and image-only pages have no native
    text to rewrite. For hybrid pages, we redact a temporary copy of the native
    text without fill and use the remaining scan pixels as the visual witness.
    """

    if page_index.classification != "hybrid" or not page_index.lines:
        return

    if not any(_line_has_potential_suspicion(line) for line in page_index.lines):
        return

    token_counts = _page_token_counts(page_index.lines)
    background_page = _make_background_witness_page(page, page_index.lines)
    try:
        for line in page_index.lines:
            _validate_line_text(background_page, line, token_counts, mode)
    finally:
        background_page.parent.close()


def _validate_line_text(page: fitz.Page, line: TextLine, token_counts: Counter[str], mode: str) -> None:
    mapped_chars = _map_line_chars(line)
    if not mapped_chars:
        return

    text_chars = list(line.text)
    corrections: list[TextLayerCorrection] = []
    handled_indices: set[int] = set()
    mapped_by_index = {mapped.index: mapped for mapped in mapped_chars}

    token_repairs = _numeric_reference_repairs(page, line.text, mapped_by_index, token_counts)
    for correction in token_repairs:
        corrections.append(correction)
        handled_indices.add(correction.index)
        if correction.decision == "corrected":
            if line.original_text is None:
                line.original_text = line.text
            text_chars[correction.index] = correction.replacement
    if token_repairs:
        line.text = "".join(text_chars)

    for mapped in mapped_chars:
        if mapped.index in handled_indices:
            continue
        if mapped.index >= len(text_chars) or text_chars[mapped.index] != mapped.char:
            continue

        signals = _suspicion_signals(line.text, mapped.index, mapped.char)
        if not signals:
            continue

        candidates = _candidate_chars(line.text, mapped.index, mapped.char, signals)
        if not candidates:
            continue

        best, original = _score_candidates(page, line.text, mapped, candidates, token_counts)
        if not best:
            continue

        decision, reason = _candidate_decision(best, original, signals, mode)
        correction = TextLayerCorrection(
            index=mapped.index,
            original=mapped.char,
            replacement=best.char,
            confidence=round(best.combined, 4),
            decision=decision,
            reason=reason,
            signals=tuple(signals),
            bbox=mapped.bbox,
            visual_scores={original.char: round(original.visual, 4), best.char: round(best.visual, 4)},
            context_scores={original.char: round(original.context, 4), best.char: round(best.context, 4)},
        )
        corrections.append(correction)

        if decision == "corrected":
            if line.original_text is None:
                line.original_text = line.text
            text_chars[mapped.index] = best.char
            line.text = "".join(text_chars)

    if corrections:
        line.text_layer_corrections.extend(corrections)


def _line_has_potential_suspicion(line: TextLine) -> bool:
    mapped_chars = _map_line_chars(line)
    mapped_by_index = {mapped.index: mapped for mapped in mapped_chars}
    if any(_repairable_numeric_reference_token(_token_span_at(line.text, index)[0]) for index in mapped_by_index):
        return True
    return any(_suspicion_signals(line.text, mapped.index, mapped.char) for mapped in mapped_chars)


def line_text_layer_rejection_reason(line: TextLine) -> str:
    for correction in line.text_layer_corrections:
        if correction.decision == "skip_line":
            return f"unresolved suspicious OCR text ({correction.original}->{correction.replacement})"
    return ""


def _map_line_chars(line: TextLine) -> list[_MappedChar]:
    result: list[_MappedChar] = []
    cursor = 0
    for run in line.runs:
        for char in run.chars:
            if not char.char:
                continue
            index = line.text.find(char.char, cursor)
            if index < 0:
                index = line.text.find(char.char)
            if index < 0:
                continue
            result.append(
                _MappedChar(
                    index=index,
                    char=char.char,
                    bbox=char.bbox,
                    origin=char.origin,
                    font_size=run.font_size,
                )
            )
            cursor = index + len(char.char)
    return result


def _suspicion_signals(text: str, index: int, char: str) -> list[str]:
    if char not in RISKY_CANDIDATES:
        return []

    if char in {"l", "I"} and _inside_alpha_word(text, index) and not _is_digit_dominated(_token_at(text, index)):
        return []
    if char in {"]", ")"} and _has_matching_open(text, index, char):
        return []

    signals: list[str] = ["risky_confusable"]
    token = _token_at(text, index)
    before = text[max(0, index - 4) : index]
    after = text[index + 1 : min(len(text), index + 5)]

    if _inside_unclosed_delimiter(text, index):
        signals.append("unclosed_delimiter_context")

    if _looks_like_numeric_reference(token):
        signals.append("numeric_reference_context")

    if char in {"J", "I", "l", "O", "S"} and _is_digit_dominated(token):
        signals.append("alpha_inside_digit_token")

    if char == "/" and _inside_alpha_word(text, index):
        signals.append("slash_inside_word")

    if char in {"J", "]", ")", "/", "1", "I", "l"} and (before.endswith("[") or re.search(r"\d$", before)):
        signals.append("thin_symbol_after_digit_or_open")

    if char in {"J", "I", "l", "1", "|"} and after[:1] in {"]", ")", ""}:
        signals.append("thin_symbol_before_close_or_line_end")

    if char in {"]", ")"} and not _has_matching_open(text, index, char):
        signals.append("closing_symbol_without_open")

    if char in {"J", "/", "]", ")"} and len(token) >= 3 and _token_has_rare_mixture(token):
        signals.append("rare_token_mixture")

    if len(signals) == 1:
        # Merely being a risky character is too broad. Use it only when it is
        # punctuation-like or in a compact non-word token.
        if char in {"J", "/", "]", ")"} and len(token) <= 8 and not token.isalpha():
            signals.append("compact_symbol_token")
        else:
            return []
    return signals


def _candidate_chars(text: str, index: int, char: str, signals: list[str]) -> list[str]:
    candidates = [candidate for candidate in RISKY_CANDIDATES.get(char, ()) if candidate != char]

    open_char = _nearest_unclosed_open(text, index)
    if open_char:
        candidates.insert(0, OPEN_TO_CLOSE[open_char])

    token = _token_at(text, index)
    if "numeric_reference_context" in signals or _is_digit_dominated(token):
        candidates.extend(["1", "]", ")"])

    deduped: list[str] = []
    seen = {char}
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped[:8]


def _numeric_reference_repairs(
    page: fitz.Page,
    text: str,
    mapped_by_index: dict[int, _MappedChar],
    token_counts: Counter[str],
) -> list[TextLayerCorrection]:
    repairs: list[TextLayerCorrection] = []
    seen_spans: set[tuple[int, int]] = set()

    for index, mapped in mapped_by_index.items():
        token, start, end = _token_span_at(text, index)
        if (start, end) in seen_spans:
            continue
        seen_spans.add((start, end))
        if not _repairable_numeric_reference_token(token):
            continue

        repaired = _repair_numeric_reference_token(token)
        if repaired == token or not _looks_like_closed_numeric_reference(repaired):
            continue

        changed = [(start + offset, old, new) for offset, (old, new) in enumerate(zip(token, repaired)) if old != new]
        if not changed:
            continue

        candidate_text = text[:start] + repaired + text[end:]
        token_context = _context_score(text, changed[-1][0], repaired[-1], token_counts)
        token_context = max(token_context, 0.90 if _balances_delimiters_better(text, candidate_text) else token_context)

        per_char: list[tuple[int, str, str, dict[str, float], float]] = []
        contradicted = False
        for absolute_index, old, new in changed:
            mapped = mapped_by_index.get(absolute_index)
            if not mapped:
                contradicted = True
                break
            visual_scores = _visual_scores(page, mapped, [old, new])
            old_visual = visual_scores.get(old, 0.0)
            new_visual = visual_scores.get(new, 0.0)
            # Digit-like substitutions are deliberately allowed with a smaller
            # visual margin because I/l/1 are often genuinely indistinguishable
            # in degraded scans. Bracket substitutions still need visual support.
            if new in {"]", ")"} and new_visual + 0.04 < old_visual:
                contradicted = True
                break
            if new.isdigit() and new_visual + 0.16 < old_visual:
                contradicted = True
                break
            per_char.append((absolute_index, old, new, visual_scores, max(old_visual, new_visual)))

        if contradicted or not per_char:
            continue

        mean_visual = sum(item[4] for item in per_char) / len(per_char)
        confidence = _bounded(0.68 * token_context + 0.32 * mean_visual)
        if confidence < 0.72:
            continue

        for absolute_index, old, new, visual_scores, _ in per_char:
            mapped = mapped_by_index[absolute_index]
            repairs.append(
                TextLayerCorrection(
                    index=absolute_index,
                    original=old,
                    replacement=new,
                    confidence=round(confidence, 4),
                    decision="corrected",
                    reason="numeric reference token repaired as a coherent unit",
                    signals=(
                        "numeric_reference_context",
                        "unclosed_delimiter_context",
                        "token_level_repair",
                    ),
                    bbox=mapped.bbox,
                    visual_scores={old: round(visual_scores.get(old, 0.0), 4), new: round(visual_scores.get(new, 0.0), 4)},
                    context_scores={old: round(_context_score(text, absolute_index, old, token_counts), 4), new: round(token_context, 4)},
                )
            )

    return repairs


def _repairable_numeric_reference_token(token: str) -> bool:
    if len(token) < 4 or len(token) > 14:
        return False
    if token[0] not in "[(":
        return False
    close = OPEN_TO_CLOSE[token[0]]
    if close in token:
        return False
    body = token[1:]
    if not any(char.isdigit() for char in body):
        return False
    allowed = set("0123456789IlJOSl|/ .:-")
    return all(char in allowed for char in body)


def _repair_numeric_reference_token(token: str) -> str:
    close = OPEN_TO_CLOSE[token[0]]
    body = list(token[1:])
    if not body:
        return token

    last_content_index = max((i for i, char in enumerate(body) if not char.isspace()), default=-1)
    for index, char in enumerate(body):
        if index == last_content_index and char in {"J", "]", ")", "/", "I", "l", "|"}:
            body[index] = close
            continue
        if char in {"I", "l", "|"}:
            body[index] = "1"
        elif char == "O":
            body[index] = "0"
        elif char == "S":
            body[index] = "5"
    return token[0] + "".join(body)


def _looks_like_closed_numeric_reference(token: str) -> bool:
    if len(token) < 4 or token[0] not in OPEN_TO_CLOSE:
        return False
    if token[-1] != OPEN_TO_CLOSE[token[0]]:
        return False
    inner = token[1:-1].replace(" ", "")
    return bool(re.fullmatch(r"[0-9.:-]{1,10}", inner))


def _score_candidates(
    page: fitz.Page,
    text: str,
    mapped: _MappedChar,
    candidates: list[str],
    token_counts: Counter[str],
) -> tuple[_CandidateScore | None, _CandidateScore]:
    chars = [mapped.char, *candidates]
    visual_scores = _visual_scores(page, mapped, chars)
    scores: list[_CandidateScore] = []
    for char in chars:
        context = _context_score(text, mapped.index, char, token_counts)
        visual = visual_scores.get(char, 0.0)
        combined = max(0.0, min(1.0, 0.72 * visual + 0.28 * context))
        scores.append(_CandidateScore(char=char, visual=visual, context=context, combined=combined))

    original = next(score for score in scores if score.char == mapped.char)
    alternatives = [score for score in scores if score.char != mapped.char]
    if not alternatives:
        return None, original
    best = max(alternatives, key=lambda score: score.combined)
    return best, original


def _visual_scores(page: fitz.Page, mapped: _MappedChar, chars: list[str]) -> dict[str, float]:
    clip = _expanded_rect(mapped.bbox, mapped.font_size)
    observed = _features_from_page(page, clip)
    if observed is None:
        return {char: 0.0 for char in chars}

    scores: dict[str, float] = {}
    for char in chars:
        template_score = _template_visual_score(observed, char, clip, mapped.origin, mapped.font_size)
        class_score = _shape_class_score(observed, char)
        scores[char] = max(template_score, class_score)
    return scores


def _template_visual_score(
    observed: _InkFeatures,
    char: str,
    clip: fitz.Rect,
    origin: tuple[float, float],
    font_size: float,
) -> float:
    template_scores: list[float] = []
    clip_key = tuple(round(value, 3) for value in (clip.x0, clip.y0, clip.x1, clip.y1))
    origin_key = (round(origin[0], 3), round(origin[1], 3))
    for font_path in REFERENCE_FONTS:
        if not font_path.exists():
            continue
        template = _template_features(char, clip_key, origin_key, round(font_size, 3), str(font_path))
        if template:
            template_scores.append(_feature_similarity(observed, template))
    return max(template_scores, default=0.0)


@lru_cache(maxsize=4096)
def _template_features(
    char: str,
    clip_tuple: tuple[float, float, float, float],
    origin: tuple[float, float],
    font_size: float,
    font_path: str,
) -> _InkFeatures | None:
    clip = fitz.Rect(clip_tuple)
    doc = fitz.open()
    try:
        page = doc.new_page(width=max(20.0, clip.width + 8.0), height=max(20.0, clip.height + 8.0))
        shifted_origin = fitz.Point(origin[0] - clip.x0 + 4.0, origin[1] - clip.y0 + 4.0)
        page.insert_text(
            shifted_origin,
            char,
            fontsize=max(1.0, font_size),
            fontfile=font_path,
            color=(0, 0, 0),
            overlay=True,
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
        return _features_from_pixmap(pix)
    finally:
        doc.close()


def _features_from_page(page: fitz.Page, clip: fitz.Rect) -> _InkFeatures | None:
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(5, 5), clip=clip, alpha=False)
    except Exception:
        return None
    return _features_from_pixmap(pix)


def _features_from_pixmap(pix: fitz.Pixmap) -> _InkFeatures | None:
    if pix.width <= 1 or pix.height <= 1:
        return None
    n = pix.n
    samples = pix.samples
    grays: list[int] = []
    for offset in range(0, len(samples), n):
        if n >= 3:
            gray = int((samples[offset] + samples[offset + 1] + samples[offset + 2]) / 3)
        else:
            gray = samples[offset]
        grays.append(gray)
    if not grays:
        return None

    med = median(grays)
    threshold = max(40, min(220, int(med - 32)))
    points: list[tuple[int, int]] = []
    width = pix.width
    for i, gray in enumerate(grays):
        if gray < threshold:
            points.append((i % width, i // width))

    min_ink = max(3, int(width * pix.height * 0.001))
    if len(points) < min_ink:
        return None

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    bbox_w = max(1, x1 - x0 + 1)
    bbox_h = max(1, y1 - y0 + 1)
    centroid_x = sum((x - x0) / bbox_w for x in xs) / len(xs)
    centroid_y = sum((y - y0) / bbox_h for y in ys) / len(ys)
    corr = _correlation([(x - x0) / bbox_w for x in xs], [(y - y0) / bbox_h for y in ys])
    verticality = 1.0 - min(1.0, _mean_row_spread(points, y0, y1) / bbox_w)

    return _InkFeatures(
        ink_count=len(points),
        fill_ratio=len(points) / max(1, bbox_w * bbox_h),
        bbox_width=bbox_w / pix.width,
        bbox_height=bbox_h / pix.height,
        aspect=bbox_w / bbox_h,
        centroid_x=centroid_x,
        centroid_y=centroid_y,
        corr_xy=corr,
        verticality=verticality,
        left_edge=_edge_density(points, x0, y0, bbox_w, bbox_h, "left"),
        right_edge=_edge_density(points, x0, y0, bbox_w, bbox_h, "right"),
        top_edge=_edge_density(points, x0, y0, bbox_w, bbox_h, "top"),
        bottom_edge=_edge_density(points, x0, y0, bbox_w, bbox_h, "bottom"),
        top_bar=_band_density(points, x0, y0, bbox_w, bbox_h, "top"),
        bottom_bar=_band_density(points, x0, y0, bbox_w, bbox_h, "bottom"),
        left_bar=_band_density(points, x0, y0, bbox_w, bbox_h, "left"),
        right_bar=_band_density(points, x0, y0, bbox_w, bbox_h, "right"),
        hook_score=_hook_score(points, x0, y0, bbox_w, bbox_h),
    )


def _shape_class_score(features: _InkFeatures, char: str) -> float:
    if char == "/":
        return _bounded(0.25 + 0.75 * abs(features.corr_xy) - 0.25 * features.verticality)
    if char == "]":
        return _bounded(
            0.18
            + 0.26 * features.verticality
            + 0.18 * features.right_bar
            + 0.18 * features.top_bar
            + 0.18 * features.bottom_bar
            - 0.15 * features.hook_score
        )
    if char == ")":
        return _bounded(
            0.20
            + 0.24 * features.right_edge
            + 0.18 * (1.0 - features.verticality)
            + 0.15 * features.centroid_x
            - 0.12 * features.top_bar
            - 0.12 * features.bottom_bar
        )
    if char == "J":
        return _bounded(0.16 + 0.28 * features.verticality + 0.28 * features.hook_score + 0.12 * features.bottom_bar)
    if char in {"1", "I", "l", "|"}:
        return _bounded(0.20 + 0.42 * features.verticality - 0.16 * features.hook_score)
    if char in {"0", "O"}:
        return _bounded(0.16 + 0.28 * (1.0 - abs(features.aspect - 0.65)) + 0.18 * features.fill_ratio)
    if char in {"5", "S"}:
        return _bounded(0.24 + 0.14 * features.top_bar + 0.14 * features.bottom_bar + 0.12 * (1.0 - features.verticality))
    return 0.0


def _feature_similarity(a: _InkFeatures, b: _InkFeatures) -> float:
    comparisons = [
        (a.bbox_width, b.bbox_width, 0.15),
        (a.bbox_height, b.bbox_height, 0.12),
        (a.aspect, b.aspect, 0.24),
        (a.centroid_x, b.centroid_x, 0.20),
        (a.centroid_y, b.centroid_y, 0.18),
        (a.corr_xy, b.corr_xy, 0.24),
        (a.verticality, b.verticality, 0.20),
        (a.top_bar, b.top_bar, 0.22),
        (a.bottom_bar, b.bottom_bar, 0.22),
        (a.left_bar, b.left_bar, 0.22),
        (a.right_bar, b.right_bar, 0.22),
        (a.hook_score, b.hook_score, 0.20),
    ]
    distance = 0.0
    weight = 0.0
    for av, bv, scale in comparisons:
        distance += min(1.0, abs(av - bv) / scale)
        weight += 1.0
    return _bounded(1.0 - distance / max(1.0, weight))


def _context_score(text: str, index: int, candidate: str, token_counts: Counter[str]) -> float:
    token = _token_at(text, index)
    candidate_text = text[:index] + candidate + text[index + 1 :]
    candidate_token = _token_at(candidate_text, index)
    score = 0.35

    if _balances_delimiters_better(text, candidate_text):
        score += 0.34
    if _looks_like_numeric_reference(candidate_token):
        score += 0.22
    if _is_digit_dominated(token) and (candidate.isdigit() or candidate in {"]", ")"}):
        score += 0.18
    if candidate in {"]", ")"} and _nearest_unclosed_open(text, index):
        score += 0.22
    if candidate == "/" and _inside_alpha_word(candidate_text, index):
        score -= 0.32
    if candidate.isalpha() and _is_digit_dominated(token):
        score -= 0.24

    original_key = _normalize_token(token)
    candidate_key = _normalize_token(candidate_token)
    if candidate_key and token_counts[candidate_key] > token_counts[original_key]:
        score += min(0.18, 0.06 * token_counts[candidate_key])

    if _token_has_rare_mixture(candidate_token):
        score -= 0.15

    return _bounded(score)


def _candidate_decision(
    best: _CandidateScore,
    original: _CandidateScore,
    signals: list[str],
    mode: str,
) -> tuple[str, str]:
    combined_margin = best.combined - original.combined
    visual_margin = best.visual - original.visual
    context_heavy = any(
        signal in signals
        for signal in (
            "unclosed_delimiter_context",
            "numeric_reference_context",
            "alpha_inside_digit_token",
            "rare_token_mixture",
        )
    )

    if (
        best.combined >= MIN_CORRECT_CONFIDENCE
        and combined_margin >= MIN_CORRECT_MARGIN
        and visual_margin >= MIN_VISUAL_MARGIN
        and best.context >= 0.50
    ):
        return "corrected", "visual and contextual evidence agree"

    if context_heavy and best.combined >= UNRESOLVED_RISK_THRESHOLD and mode == "conservative":
        return "skip_line", "suspicious OCR token was not visually decisive"

    if context_heavy:
        return "flagged", "suspicious OCR token; evidence below correction threshold"

    return "unchanged", "confusable character inspected; original not clearly worse"


def _make_background_witness_page(page: fitz.Page, lines: list[TextLine]) -> fitz.Page:
    source_doc = page.parent
    temp = fitz.open()
    temp.insert_pdf(source_doc, from_page=page.number, to_page=page.number)
    witness = temp[0]
    for line in lines:
        for run in line.runs:
            try:
                witness.add_redact_annot(fitz.Rect(run.bbox) + (-0.8, -0.8, 0.8, 0.8), fill=False)
            except TypeError:
                witness.add_redact_annot(fitz.Rect(run.bbox) + (-0.8, -0.8, 0.8, 0.8), fill=None)
    witness.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )
    return witness


def _expanded_rect(rect: RectTuple, font_size: float) -> fitz.Rect:
    base = fitz.Rect(rect)
    pad_x = max(0.8, min(3.0, font_size * 0.14))
    pad_y = max(0.8, min(3.0, font_size * 0.18))
    return base + (-pad_x, -pad_y, pad_x, pad_y)


def _token_at(text: str, index: int) -> str:
    token, _, _ = _token_span_at(text, index)
    return token


def _token_span_at(text: str, index: int) -> tuple[str, int, int]:
    allowed = set(string.ascii_letters + string.digits + "[](){}./:-_")
    start = index
    while start > 0 and text[start - 1] in allowed:
        start -= 1
    end = index + 1
    while end < len(text) and text[end] in allowed:
        end += 1
    return text[start:end], start, end


def _page_token_counts(lines: list[TextLine]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for line in lines:
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}|\[[0-9A-Za-z./:-]+\]?", line.text):
            normalized = _normalize_token(token)
            if normalized:
                counter[normalized] += 1
    return counter


def _normalize_token(token: str) -> str:
    return token.strip(string.punctuation).lower()


def _inside_unclosed_delimiter(text: str, index: int) -> bool:
    return _nearest_unclosed_open(text, index) is not None


def _nearest_unclosed_open(text: str, index: int) -> str | None:
    left = text[max(0, index - 20) : index]
    for open_char, close_char in OPEN_TO_CLOSE.items():
        if left.rfind(open_char) > left.rfind(close_char):
            return open_char
    return None


def _has_matching_open(text: str, index: int, close_char: str) -> bool:
    open_char = {"]": "[", ")": "(", "}": "{"}.get(close_char)
    if not open_char:
        return False
    return text.rfind(open_char, 0, index) > text.rfind(close_char, 0, index)


def _balances_delimiters_better(original: str, candidate: str) -> bool:
    return _delimiter_imbalance(candidate) < _delimiter_imbalance(original)


def _delimiter_imbalance(text: str) -> int:
    imbalance = 0
    for open_char, close_char in OPEN_TO_CLOSE.items():
        imbalance += abs(text.count(open_char) - text.count(close_char))
    return imbalance


def _looks_like_numeric_reference(token: str) -> bool:
    compact = token.strip()
    if len(compact) < 3:
        return False
    if re.fullmatch(r"[\[(]?[0-9IlJ/|l .:-]{1,8}[\])]?", compact):
        return any(char.isdigit() for char in compact)
    if re.fullmatch(r"p\.?[0-9IlJ/|l .:-]{1,8}", compact.lower()):
        return True
    return False


def _is_digit_dominated(token: str) -> bool:
    alnum = [char for char in token if char.isalnum()]
    if not alnum:
        return False
    digits = sum(char.isdigit() for char in alnum)
    thin_alpha = sum(char in "IlJOSl" for char in alnum)
    return digits >= 1 and (digits + thin_alpha) / len(alnum) >= 0.65


def _inside_alpha_word(text: str, index: int) -> bool:
    return index > 0 and index + 1 < len(text) and text[index - 1].isalpha() and text[index + 1].isalpha()


def _token_has_rare_mixture(token: str) -> bool:
    has_digit = any(char.isdigit() for char in token)
    has_upper = any(char.isupper() for char in token)
    has_punct = any(char in "[]()/|" for char in token)
    return has_digit and has_upper and has_punct


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return num / (den_x * den_y)


def _mean_row_spread(points: list[tuple[int, int]], y0: int, y1: int) -> float:
    spreads: list[float] = []
    for y in range(y0, y1 + 1):
        xs = [x for x, py in points if py == y]
        if len(xs) > 1:
            spreads.append(max(xs) - min(xs))
    return sum(spreads) / len(spreads) if spreads else 0.0


def _edge_density(points: list[tuple[int, int]], x0: int, y0: int, width: int, height: int, edge: str) -> float:
    band = max(1, int((width if edge in {"left", "right"} else height) * 0.18))
    if edge == "left":
        count = sum(1 for x, _ in points if x - x0 < band)
        denom = band * height
    elif edge == "right":
        count = sum(1 for x, _ in points if x0 + width - 1 - x < band)
        denom = band * height
    elif edge == "top":
        count = sum(1 for _, y in points if y - y0 < band)
        denom = band * width
    else:
        count = sum(1 for _, y in points if y0 + height - 1 - y < band)
        denom = band * width
    return min(1.0, count / max(1, denom))


def _band_density(points: list[tuple[int, int]], x0: int, y0: int, width: int, height: int, band_name: str) -> float:
    if band_name in {"top", "bottom"}:
        band = max(1, int(height * 0.22))
        band_points = [(x, y) for x, y in points if (y - y0 < band if band_name == "top" else y0 + height - 1 - y < band)]
        return len({x for x, _ in band_points}) / max(1, width)
    band = max(1, int(width * 0.22))
    band_points = [(x, y) for x, y in points if (x - x0 < band if band_name == "left" else x0 + width - 1 - x < band)]
    return len({y for _, y in band_points}) / max(1, height)


def _hook_score(points: list[tuple[int, int]], x0: int, y0: int, width: int, height: int) -> float:
    bottom_band = max(1, int(height * 0.30))
    bottom = [(x, y) for x, y in points if y0 + height - 1 - y < bottom_band]
    if not bottom:
        return 0.0
    left_reach = sum(1 for x, _ in bottom if (x - x0) / max(1, width) < 0.42)
    bottom_coverage = len({x for x, _ in bottom}) / max(1, width)
    return min(1.0, 0.55 * (left_reach / len(bottom)) + 0.45 * bottom_coverage)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))
