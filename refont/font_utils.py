from __future__ import annotations

from functools import lru_cache
from statistics import median
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont

from .models import FontInfo, FontSegment, FontVisualProfile


PROJECT_FONTS_DIR = Path(__file__).resolve().parent / "fonts"

SYSTEM_CJK_CANDIDATES = [
    PROJECT_FONTS_DIR / "NotoSansCJKsc-Regular.otf",
    PROJECT_FONTS_DIR / "NotoSansSC-Regular.otf",
    PROJECT_FONTS_DIR / "NotoSerifCJKsc-Regular.otf",
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/NotoSansCJKsc-Regular.otf"),
    Path("/Library/Fonts/NotoSansSC-Regular.otf"),
]


def is_cjk_codepoint(codepoint: int) -> bool:
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
        or 0x3000 <= codepoint <= 0x303F
        or 0xFF00 <= codepoint <= 0xFFEF
    )


def is_private_use(codepoint: int) -> bool:
    return (
        0xE000 <= codepoint <= 0xF8FF
        or 0xF0000 <= codepoint <= 0xFFFFD
        or 0x100000 <= codepoint <= 0x10FFFD
    )


def is_ignorable_for_coverage(char: str) -> bool:
    return char.isspace() or ord(char) in (0x00AD, 0x200B, 0xFEFF)


def resolve_cjk_fallback(explicit_path: str | Path | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"CJK fallback font not found: {path}")
        return path

    for candidate in SYSTEM_CJK_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def build_font_chain(target_font: str | Path, cjk_fallback: str | Path | None = None) -> list[FontInfo]:
    target = load_font_info(Path(target_font).expanduser().resolve(), "target")
    chain = [target]

    fallback_path = resolve_cjk_fallback(cjk_fallback)
    if fallback_path and fallback_path.resolve() != target.path:
        chain.append(load_font_info(fallback_path.resolve(), "cjk-fallback"))

    return chain


@lru_cache(maxsize=32)
def load_font_info(path: Path, label: str = "font", font_index: int = 0) -> FontInfo:
    if not path.exists():
        raise FileNotFoundError(f"Font file not found: {path}")

    font = _open_ttfont(path, font_index)
    try:
        cmap: set[int] = set()
        for table in font["cmap"].tables:
            if table.isUnicode():
                cmap.update(int(codepoint) for codepoint in table.cmap.keys())

        head = font["head"]
        hhea = font["hhea"]
        upem = int(head.unitsPerEm)
        ascender = int(getattr(hhea, "ascent", upem))
        descender = int(getattr(hhea, "descent", -round(upem * 0.25)))

        if "OS/2" in font:
            os2 = font["OS/2"]
            ascender = int(getattr(os2, "sTypoAscender", ascender) or ascender)
            descender = int(getattr(os2, "sTypoDescender", descender) or descender)

        return FontInfo(
            path=path,
            label=label,
            upem=upem,
            ascender=ascender,
            descender=descender,
            cmap=frozenset(cmap),
            font_index=font_index,
        )
    finally:
        font.close()


@lru_cache(maxsize=32)
def build_font_visual_profile(path: Path, font_index: int = 0) -> FontVisualProfile:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Font file not found: {path}")

    font = _open_ttfont(path, font_index)
    try:
        cmap: dict[int, str] = {}
        for table in font["cmap"].tables:
            if table.isUnicode():
                cmap.update({int(codepoint): glyph_name for codepoint, glyph_name in table.cmap.items()})

        head = font["head"]
        hhea = font["hhea"]
        upem = int(head.unitsPerEm)
        os2 = font["OS/2"] if "OS/2" in font else None
        post = font["post"] if "post" in font else None

        typo_ascender = int(getattr(os2, "sTypoAscender", getattr(hhea, "ascent", upem)) if os2 else getattr(hhea, "ascent", upem))
        typo_descender = int(getattr(os2, "sTypoDescender", getattr(hhea, "descent", -round(upem * 0.25))) if os2 else getattr(hhea, "descent", -round(upem * 0.25)))
        typo_line_gap = int(getattr(os2, "sTypoLineGap", 0) if os2 else 0)
        hhea_ascender = int(getattr(hhea, "ascent", typo_ascender))
        hhea_descender = int(getattr(hhea, "descent", typo_descender))
        hhea_line_gap = int(getattr(hhea, "lineGap", 0))
        win_ascent = int(getattr(os2, "usWinAscent", max(0, hhea_ascender)) if os2 else max(0, hhea_ascender))
        win_descent = int(getattr(os2, "usWinDescent", abs(hhea_descender)) if os2 else abs(hhea_descender))

        glyph_set = font.getGlyphSet()
        x_height = _sane_metric(getattr(os2, "sxHeight", None) if os2 else None, upem, 0.35, 0.80)
        if x_height is None:
            x_height = _median_glyph_height(font, glyph_set, cmap, "x")
        if x_height is None:
            x_height = _median_glyph_height(font, glyph_set, cmap, "aenosuvwxz")

        cap_height = _sane_metric(getattr(os2, "sCapHeight", None) if os2 else None, upem, 0.50, 0.95)
        if cap_height is None:
            cap_height = _median_glyph_height(font, glyph_set, cmap, "H")
        if cap_height is None:
            cap_height = _median_glyph_height(font, glyph_set, cmap, "AEHINOTX")

        digit_height = _median_glyph_height(font, glyph_set, cmap, "0123456789")
        if digit_height is None:
            digit_height = cap_height

        cjk_bounds = _union_glyph_bounds(font, glyph_set, cmap, "一中国語漢字日月田")
        ideographic_top = int(cjk_bounds[3]) if cjk_bounds else None
        ideographic_bottom = int(cjk_bounds[1]) if cjk_bounds else None
        supports_cjk = any(is_cjk_codepoint(codepoint) for codepoint in cmap)

        return FontVisualProfile(
            font_id=f"{path}:{font_index}",
            path=path,
            face_index=font_index,
            upem=upem,
            typo_ascender=typo_ascender,
            typo_descender=typo_descender,
            typo_line_gap=typo_line_gap,
            hhea_ascender=hhea_ascender,
            hhea_descender=hhea_descender,
            hhea_line_gap=hhea_line_gap,
            win_ascent=win_ascent,
            win_descent=win_descent,
            x_height=int(x_height) if x_height else None,
            cap_height=int(cap_height) if cap_height else None,
            digit_height=int(digit_height) if digit_height else None,
            ideographic_top=ideographic_top,
            ideographic_bottom=ideographic_bottom,
            global_bbox=(int(head.xMin), int(head.yMin), int(head.xMax), int(head.yMax)),
            is_monospace=bool(getattr(post, "isFixedPitch", 0)) if post else False,
            supports_cjk=supports_cjk,
            cmap_codepoints=frozenset(cmap.keys()),
        )
    finally:
        font.close()


def build_visual_profile_chain(font_chain: list[FontInfo]) -> dict[str, FontVisualProfile]:
    return {
        str(font.path): build_font_visual_profile(font.path, font.font_index)
        for font in font_chain
    }


def _sane_metric(value: object, upem: int, low: float, high: float) -> int | None:
    try:
        metric = int(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if int(upem * low) <= metric <= int(upem * high):
        return metric
    return None


def _median_glyph_height(font: TTFont, glyph_set, cmap: dict[int, str], chars: str) -> int | None:
    heights: list[int] = []
    for char in chars:
        glyph_name = cmap.get(ord(char))
        if not glyph_name:
            continue
        bounds = _glyph_bounds(font, glyph_set, glyph_name)
        if bounds:
            heights.append(int(bounds[3] - bounds[1]))
    return int(median(heights)) if heights else None


def _union_glyph_bounds(font: TTFont, glyph_set, cmap: dict[int, str], chars: str) -> tuple[int, int, int, int] | None:
    bounds_list = []
    for char in chars:
        glyph_name = cmap.get(ord(char))
        if glyph_name:
            bounds = _glyph_bounds(font, glyph_set, glyph_name)
            if bounds:
                bounds_list.append(bounds)
    if len(bounds_list) < 3:
        return None
    x0 = min(bounds[0] for bounds in bounds_list)
    y0 = min(bounds[1] for bounds in bounds_list)
    x1 = max(bounds[2] for bounds in bounds_list)
    y1 = max(bounds[3] for bounds in bounds_list)
    return (int(x0), int(y0), int(x1), int(y1))


def _glyph_bounds(font: TTFont, glyph_set, glyph_name: str) -> tuple[int, int, int, int] | None:
    try:
        pen = BoundsPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
    except Exception:
        return None
    if not pen.bounds:
        return None
    return tuple(int(value) for value in pen.bounds)  # type: ignore[return-value]


def _open_ttfont(path: Path, font_index: int) -> TTFont:
    suffix = path.suffix.lower()
    if suffix in {".ttc", ".otc"}:
        collection = TTCollection(path)
        try:
            font = collection.fonts[font_index]
            # TTCollection owns the file handle; TTFont tables are already loaded lazily.
            font.reader.file.seek(0)
            return TTFont(path, fontNumber=font_index)
        finally:
            collection.close()
    return TTFont(path)


def missing_codepoints(text: str, font_chain: list[FontInfo]) -> list[int]:
    missing: list[int] = []
    for char in text:
        if is_ignorable_for_coverage(char):
            continue
        codepoint = ord(char)
        if not any(font.covers(codepoint) for font in font_chain):
            missing.append(codepoint)
    return missing


def segment_by_font_coverage(text: str, font_chain: list[FontInfo]) -> list[FontSegment]:
    if not font_chain:
        return []

    segments: list[FontSegment] = []
    current_font = font_chain[0]
    current_chars: list[str] = []
    current_script = "latin"
    start_index = 0

    for index, char in enumerate(text):
        chosen = choose_font_for_char(char, font_chain, current_font)
        script = "cjk" if is_cjk_codepoint(ord(char)) else "latin"

        if current_chars and (chosen.path != current_font.path or script != current_script):
            segments.append(
                FontSegment(
                    text="".join(current_chars),
                    font=current_font,
                    script=current_script,
                    start_index=start_index,
                )
            )
            current_chars = []
            start_index = index

        current_font = chosen
        current_script = script
        current_chars.append(char)

    if current_chars:
        segments.append(
            FontSegment(
                text="".join(current_chars),
                font=current_font,
                script=current_script,
                start_index=start_index,
            )
        )

    return segments


def choose_font_for_char(char: str, font_chain: list[FontInfo], preferred: FontInfo | None = None) -> FontInfo:
    if is_ignorable_for_coverage(char):
        return preferred or font_chain[0]

    codepoint = ord(char)
    for font in font_chain:
        if font.covers(codepoint):
            return font
    return font_chain[0]
