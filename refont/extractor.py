from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import isfinite
from statistics import median

import fitz

from .font_utils import is_cjk_codepoint
from .models import CharGeometry, PageIndex, RectTuple, TextLine, TextRun


BASELINE_TOLERANCE_PT = 2.0


def extract_page_index(page: fitz.Page, page_no: int, classification: str) -> PageIndex:
    lines = group_runs_into_lines(extract_text_runs(page)) if classification in {"native", "hybrid"} else []
    return PageIndex(
        page_no=page_no,
        width_pt=float(page.rect.width),
        height_pt=float(page.rect.height),
        rotation=int(page.rotation),
        classification=classification,  # type: ignore[arg-type]
        lines=lines,
    )


def extract_text_runs(page: fitz.Page) -> list[TextRun]:
    runs = _runs_from_texttrace(page)
    if runs:
        return runs
    return _runs_from_rawdict(page)


def group_runs_into_lines(runs: list[TextRun]) -> list[TextLine]:
    visible_runs = [run for run in runs if _rect_area(run.bbox) > 0.01]
    clusters: list[list[TextRun]] = []

    for run in sorted(visible_runs, key=lambda item: (item.seqno, item.origin[1], item.origin[0])):
        placed = False
        for cluster in clusters:
            if _same_line(cluster[0], run):
                cluster.append(run)
                placed = True
                break
        if not placed:
            clusters.append([run])

    lines: list[TextLine] = []
    for cluster in clusters:
        direction = _cluster_direction(cluster)
        if direction == "rtl":
            ordered = sorted(cluster, key=lambda item: item.bbox[2], reverse=True)
        elif direction == "ttb":
            ordered = sorted(cluster, key=lambda item: item.bbox[1])
        else:
            ordered = sorted(cluster, key=lambda item: item.bbox[0])

        text = _join_runs_for_line(ordered)
        bbox = _union_rects(run.bbox for run in ordered)
        baseline_y = _line_baseline_y(ordered)
        lines.append(
            TextLine(
                text=text,
                bbox=bbox,
                baseline_y=baseline_y,
                direction=direction,
                runs=ordered,
            )
        )

    return sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))


def _runs_from_texttrace(page: fitz.Page) -> list[TextRun]:
    try:
        traces = page.get_texttrace()
    except Exception:
        return []

    runs: list[TextRun] = []
    for index, span in enumerate(traces):
        render_mode = _render_mode(span)
        source = "invisible-ocr" if render_mode == 3 or _trace_type(span) == "ignore-text" else "native"
        direction = _direction_from_trace(span)
        runs.extend(_line_runs_from_trace_span(span, index, source, direction, render_mode))
    return runs


def _line_runs_from_trace_span(
    span: dict,
    fallback_seqno: int,
    source: str,
    direction: str,
    render_mode: int | None,
) -> list[TextRun]:
    chars = span.get("chars", [])
    clusters = _cluster_trace_chars_by_baseline(chars)
    if not clusters:
        text = _text_from_trace_chars(chars)
        bbox = _valid_bbox(span.get("bbox")) or _bbox_from_trace_chars(chars)
        if not bbox:
            return []
        origin = _origin_from_trace_chars(chars) or (bbox[0], bbox[3])
        clusters = [(text, bbox, origin, _trace_char_geometries(chars))]

    runs: list[TextRun] = []
    for text, bbox, origin, char_geometries in clusters:
        if not text and _rect_area(bbox) <= 0.01:
            continue
        runs.append(
            TextRun(
                text=text,
                bbox=bbox,
                origin=origin,
                font_name=str(span.get("font", "")),
                font_size=float(span.get("size", max(1.0, bbox[3] - bbox[1]))),
                color=span.get("color", 0),
                opacity=_opacity(span),
                seqno=int(span.get("seqno", fallback_seqno)),
                source=source,  # type: ignore[arg-type]
                flags=_flags_from_int(int(span.get("flags", 0) or 0)),
                direction=direction,  # type: ignore[arg-type]
                render_mode=render_mode,
                chars=char_geometries,
            )
        )
    return runs


def _cluster_trace_chars_by_baseline(chars: Sequence[object]) -> list[tuple[str, RectTuple, tuple[float, float], list[CharGeometry]]]:
    clusters: list[tuple[list[str], list[RectTuple], tuple[float, float], list[CharGeometry]]] = []
    current_text: list[str] = []
    current_rects: list[RectTuple] = []
    current_chars: list[CharGeometry] = []
    current_origin: tuple[float, float] | None = None
    current_baseline: float | None = None

    def flush() -> None:
        nonlocal current_text, current_rects, current_chars, current_origin, current_baseline
        if current_text and current_rects and current_origin:
            clusters.append((current_text, current_rects, current_origin, current_chars))
        current_text = []
        current_rects = []
        current_chars = []
        current_origin = None
        current_baseline = None

    for char in chars:
        text = _char_text(char)
        origin = _char_origin(char)
        bbox = _char_bbox(char)
        if origin is None or bbox is None:
            continue

        baseline = origin[1]
        if current_baseline is not None and abs(baseline - current_baseline) > BASELINE_TOLERANCE_PT:
            flush()

        if current_origin is None:
            current_origin = origin
            current_baseline = baseline
        current_text.append(text)
        current_rects.append(bbox)
        current_chars.append(CharGeometry(char=text, bbox=bbox, origin=origin))

    flush()

    return [
        ("".join(text), _union_rects(rects), origin, char_geometries)
        for text, rects, origin, char_geometries in clusters
    ]


def _trace_char_geometries(chars: Sequence[object]) -> list[CharGeometry]:
    result: list[CharGeometry] = []
    for char in chars:
        text = _char_text(char)
        origin = _char_origin(char)
        bbox = _char_bbox(char)
        if origin is None or bbox is None:
            continue
        result.append(CharGeometry(char=text, bbox=bbox, origin=origin))
    return result


def _runs_from_rawdict(page: fitz.Page) -> list[TextRun]:
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return []

    runs: list[TextRun] = []
    seqno = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = _direction_from_raw_line(line)
            for span in line.get("spans", []):
                text = span.get("text") or "".join(char.get("c", "") for char in span.get("chars", []))
                bbox = _valid_bbox(span.get("bbox"))
                if not bbox:
                    continue
                origin = _origin_from_raw_chars(span.get("chars", [])) or (bbox[0], bbox[3])
                flags = _flags_from_int(int(span.get("flags", 0)))
                runs.append(
                    TextRun(
                        text=text,
                        bbox=bbox,
                        origin=origin,
                        font_name=str(span.get("font", "")),
                        font_size=float(span.get("size", max(1.0, bbox[3] - bbox[1]))),
                        color=span.get("color", 0),
                        opacity=1.0,
                        seqno=seqno,
                        source="native",
                        flags=flags,
                        direction=direction,  # type: ignore[arg-type]
                        chars=_raw_char_geometries(span.get("chars", [])),
                    )
                )
                seqno += 1
    return runs


def _line_baseline_y(runs: list[TextRun]) -> float:
    """Char-count-weighted median origin of the dominant-size runs.

    A mean over all runs lets superscripts, footnote markers, and slightly
    raised small runs drag the drawn baseline off the true text baseline.
    Runs whose font size differs materially from the line's median size are
    excluded from the estimate (their text still belongs to the line).
    """
    sizes = [run.font_size for run in runs if run.font_size > 0]
    median_size = float(median(sizes)) if sizes else 0.0
    dominant = [
        run
        for run in runs
        if median_size <= 0 or abs(run.font_size - median_size) <= 0.20 * median_size
    ]
    if not dominant:
        dominant = runs

    weighted: list[float] = []
    for run in dominant:
        count = max(1, sum(1 for char in run.text if not char.isspace()))
        weighted.extend([run.origin[1]] * min(count, 80))
    return float(median(weighted))


def _same_line(a: TextRun, b: TextRun) -> bool:
    if a.direction != b.direction:
        return False
    return abs(a.origin[1] - b.origin[1]) <= BASELINE_TOLERANCE_PT


def _cluster_direction(cluster: list[TextRun]) -> str:
    counts: dict[str, int] = {}
    for run in cluster:
        counts[run.direction] = counts.get(run.direction, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0] if counts else "unknown"


def _join_runs_for_line(runs: list[TextRun]) -> str:
    pieces: list[str] = []
    previous: TextRun | None = None
    for run in runs:
        if previous and _should_insert_space(previous, run):
            pieces.append(" ")
        pieces.append(run.text)
        previous = run
    return _normalize_visual_text("".join(pieces))


def _normalize_visual_text(text: str) -> str:
    # Searchable scans often expose visible line-break hyphens as U+00AD.
    # Inserted target fonts may render that codepoint invisibly or as tofu, so
    # normalize it to an ordinary visible hyphen for visual PDF rewriting.
    return text.replace("\u00ad", "-")


def _should_insert_space(left: TextRun, right: TextRun) -> bool:
    if not left.text or not right.text:
        return False
    if left.text[-1].isspace() or right.text[0].isspace():
        return False
    if is_cjk_codepoint(ord(left.text[-1])) or is_cjk_codepoint(ord(right.text[0])):
        return False
    gap = right.bbox[0] - left.bbox[2]
    threshold = max(2.0, min(left.font_size, right.font_size) * 0.35)
    return gap > threshold


def _text_from_trace_chars(chars: Sequence[object]) -> str:
    text: list[str] = []
    for char in chars:
        text.append(_char_text(char))
    return "".join(text)


def _char_text(char: object) -> str:
    value: object | None = None
    if isinstance(char, dict):
        value = char.get("c") or char.get("text") or char.get("unicode")
    elif isinstance(char, (tuple, list)) and char:
        value = char[0]

    if isinstance(value, str):
        return value
    if isinstance(value, int) and 0 <= value <= 0x10FFFF:
        return chr(value)
    return ""


def _bbox_from_trace_chars(chars: Sequence[object]) -> RectTuple | None:
    rects: list[RectTuple] = []
    for char in chars:
        valid = _char_bbox(char)
        if valid:
            rects.append(valid)
    return _union_rects(rects) if rects else None


def _char_bbox(char: object) -> RectTuple | None:
    bbox = None
    if isinstance(char, dict):
        bbox = char.get("bbox")
    elif isinstance(char, (tuple, list)) and len(char) >= 4:
        bbox = char[3]
    return _valid_bbox(bbox)


def _origin_from_trace_chars(chars: Sequence[object]) -> tuple[float, float] | None:
    for char in chars:
        point = _char_origin(char)
        if point:
            return point
    return None


def _char_origin(char: object) -> tuple[float, float] | None:
    origin = None
    if isinstance(char, dict):
        origin = char.get("origin")
    elif isinstance(char, (tuple, list)) and len(char) >= 3:
        origin = char[2]
    return _valid_point(origin)


def _origin_from_raw_chars(chars: Sequence[object]) -> tuple[float, float] | None:
    for char in chars:
        if isinstance(char, dict):
            point = _valid_point(char.get("origin"))
            if point:
                return point
    return None


def _raw_char_geometries(chars: Sequence[object]) -> list[CharGeometry]:
    result: list[CharGeometry] = []
    for char in chars:
        if not isinstance(char, dict):
            continue
        text = str(char.get("c", ""))
        bbox = _valid_bbox(char.get("bbox"))
        origin = _valid_point(char.get("origin"))
        if text and bbox and origin:
            result.append(CharGeometry(char=text, bbox=bbox, origin=origin))
    return result


def _direction_from_trace(span: dict) -> str:
    if int(span.get("wmode", 0) or 0) == 1:
        return "ttb"
    direction = span.get("dir")
    if isinstance(direction, str):
        return direction if direction in {"ltr", "rtl", "ttb"} else "unknown"
    if isinstance(direction, (tuple, list)) and len(direction) >= 2:
        dx = float(direction[0])
        dy = float(direction[1])
        if abs(dy) > 0.05:
            return "ttb" if abs(dy) > abs(dx) else "rotated"
        return "rtl" if dx < 0 else "ltr"
    return "unknown"


def _direction_from_raw_line(line: dict) -> str:
    direction = line.get("dir")
    if isinstance(direction, (tuple, list)) and len(direction) >= 2:
        dx = float(direction[0])
        dy = float(direction[1])
        if abs(dy) > 0.05:
            return "ttb" if abs(dy) > abs(dx) else "rotated"
        return "rtl" if dx < 0 else "ltr"
    return "ltr"


def _render_mode(span: dict) -> int | None:
    for key in ("render_mode", "renderMode", "type"):
        value = span.get(key)
        if isinstance(value, int):
            return value
    return None


def _trace_type(span: dict) -> str:
    value = span.get("type")
    return value if isinstance(value, str) else ""


def _opacity(span: dict) -> float:
    value = span.get("opacity", 1.0)
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    try:
        return float(value)
    except Exception:
        return 1.0


def _flags_from_int(flags: int) -> list[str]:
    labels: list[str] = []
    if flags & 2:
        labels.append("italic")
    if flags & 16:
        labels.append("bold")
    return labels


def _valid_bbox(value: object) -> RectTuple | None:
    try:
        rect = fitz.Rect(value)  # type: ignore[arg-type]
    except Exception:
        return None
    coords = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
    if all(isfinite(coord) for coord in coords) and coords[2] >= coords[0] and coords[3] >= coords[1]:
        return coords
    return None


def _valid_point(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except Exception:
        return None
    if isfinite(x) and isfinite(y):
        return (x, y)
    return None


def _union_rects(rects: Iterable[RectTuple]) -> RectTuple:
    iterator = iter(rects)
    first = next(iterator)
    x0, y0, x1, y1 = first
    for rect in iterator:
        x0 = min(x0, rect[0])
        y0 = min(y0, rect[1])
        x1 = max(x1, rect[2])
        y1 = max(y1, rect[3])
    return (x0, y0, x1, y1)


def _rect_area(rect: RectTuple) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])
