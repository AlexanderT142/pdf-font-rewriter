from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


RectTuple = tuple[float, float, float, float]
PointTuple = tuple[float, float]


@dataclass(frozen=True)
class FontInfo:
    path: Path
    label: str
    upem: int
    ascender: int
    descender: int
    cmap: frozenset[int]
    font_index: int = 0

    def covers(self, codepoint: int) -> bool:
        return codepoint in self.cmap


class LineRole(str, Enum):
    BODY = "body"
    HEADING = "heading"
    RUNNING_HEADER = "running_header"
    PAGE_NUMBER = "page_number"
    FOOTNOTE = "footnote"
    CAPTION = "caption"
    CJK_BODY = "cjk_body"
    MIXED_LATIN_CJK = "mixed_latin_cjk"
    UNKNOWN = "unknown"


class VisualMetricKind(str, Enum):
    X_HEIGHT = "x_height"
    CAP_HEIGHT = "cap_height"
    DIGIT_HEIGHT = "digit_height"
    IDEOGRAPHIC_HEIGHT = "ideographic_height"
    ACTUAL_LINE_INK = "actual_line_ink"


class AnchorMode(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass(frozen=True)
class FontVisualProfile:
    font_id: str
    path: Path
    face_index: int
    upem: int
    typo_ascender: int
    typo_descender: int
    typo_line_gap: int
    hhea_ascender: int
    hhea_descender: int
    hhea_line_gap: int
    win_ascent: int
    win_descent: int
    x_height: int | None
    cap_height: int | None
    digit_height: int | None
    ideographic_top: int | None
    ideographic_bottom: int | None
    global_bbox: tuple[int, int, int, int]
    is_monospace: bool
    supports_cjk: bool
    cmap_codepoints: frozenset[int]


@dataclass(frozen=True)
class FontSegment:
    text: str
    font: FontInfo
    script: str
    start_index: int


@dataclass(frozen=True)
class CharGeometry:
    char: str
    bbox: RectTuple
    origin: PointTuple


@dataclass(frozen=True)
class TextLayerCorrection:
    index: int
    original: str
    replacement: str
    confidence: float
    decision: Literal["corrected", "flagged", "unchanged", "skip_line"]
    reason: str
    signals: tuple[str, ...]
    bbox: RectTuple | None = None
    visual_scores: dict[str, float] = field(default_factory=dict)
    context_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CharVisualStats:
    lower_mid_count: int
    lower_mid_height_pt: float | None
    cap_count: int
    cap_height_pt: float | None
    digit_count: int
    digit_height_pt: float | None
    cjk_count: int
    cjk_height_pt: float | None
    nonspace_count: int
    nonspace_height_pt: float


@dataclass(frozen=True)
class OriginalLineVisual:
    bbox: RectTuple
    nonspace_bbox: RectTuple
    baseline_y: float
    orig_top_pt: float
    orig_bottom_pt: float
    orig_ink_height_pt: float
    orig_advance_pt: float
    anchor_mode: AnchorMode
    anchor_x: float
    char_stats: CharVisualStats


@dataclass(frozen=True)
class ShapedMeasure:
    font_id: str
    text: str
    script: str
    advance_du: float
    ink_x_min_du: float
    ink_x_max_du: float
    ink_y_min_du: float
    ink_y_max_du: float
    glyph_count: int
    cluster_count: int
    has_notdef: bool


@dataclass(frozen=True)
class SegmentFitPlan:
    text: str
    font: FontInfo
    script: str
    size_pt: float
    unscaled_advance_pt: float
    x_offset_unscaled_pt: float


@dataclass(frozen=True)
class VisualFitDecision:
    safe: bool
    role: LineRole
    confidence: float
    metric_used: VisualMetricKind | None
    original_metric_pt: float | None
    target_metric_du: float | None
    raw_size_pt: float | None
    final_size_pt: float | None
    scale_x: float | None
    target_top_pt: float | None
    target_bottom_pt: float | None
    anchor_mode: AnchorMode
    anchor_x: float
    segments: tuple[SegmentFitPlan, ...]
    reject_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualFitThresholds:
    body_scale: tuple[float, float] = (0.92, 1.08)
    heading_scale: tuple[float, float] = (0.92, 1.08)
    running_header_scale: tuple[float, float] = (0.92, 1.08)
    page_number_scale: tuple[float, float] = (0.90, 1.08)
    footnote_scale: tuple[float, float] = (0.92, 1.08)
    caption_scale: tuple[float, float] = (0.92, 1.08)
    cjk_scale: tuple[float, float] = (0.97, 1.03)
    mixed_scale: tuple[float, float] = (0.95, 1.05)
    hard_scale: tuple[float, float] = (0.90, 1.08)
    min_role_confidence: float = 0.55
    strict_unknown: bool = True


@dataclass
class FitResult:
    font_size: float
    scale_x: float
    method: str
    target_advance: float
    segments: list[FontSegment] = field(default_factory=list)
    segment_sizes: list[float] = field(default_factory=list)
    visual_decision: VisualFitDecision | None = None
    unsafe_reason: str = ""

    @property
    def safe(self) -> bool:
        return self.method != "unsafe"


@dataclass
class TextRun:
    text: str
    bbox: RectTuple
    origin: PointTuple
    font_name: str
    font_size: float
    color: int | tuple[float, ...]
    opacity: float
    seqno: int
    source: Literal["native", "invisible-ocr"]
    flags: list[str]
    direction: Literal["ltr", "rtl", "ttb", "rotated", "unknown"] = "unknown"
    render_mode: int | None = None
    chars: list[CharGeometry] = field(default_factory=list)


@dataclass
class TextLine:
    text: str
    bbox: RectTuple
    baseline_y: float
    direction: Literal["ltr", "rtl", "ttb", "rotated", "unknown"]
    runs: list[TextRun]
    original_text: str | None = None
    text_layer_corrections: list[TextLayerCorrection] = field(default_factory=list)
    safety: Literal["unknown", "safe", "unsafe"] = "unknown"
    unsafe_reasons: list[str] = field(default_factory=list)
    fit_result: FitResult | None = None


@dataclass
class PageIndex:
    page_no: int
    width_pt: float
    height_pt: float
    rotation: int
    classification: Literal["native", "scanned", "hybrid", "unknown", "not_selected"]
    lines: list[TextLine] = field(default_factory=list)
    safe_line_count: int = 0
    unsafe_line_count: int = 0
    region_decisions: list[dict] = field(default_factory=list)
