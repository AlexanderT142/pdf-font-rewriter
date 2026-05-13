from __future__ import annotations

import fitz


def classify_page(page: fitz.Page) -> str:
    """Return native, scanned, hybrid, or unknown."""
    text_dict = page.get_text("dict")
    has_native_text = any(
        span.get("text", "").strip()
        for block in text_dict.get("blocks", [])
        if block.get("type") == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )
    has_large_image = any(img_bbox_covers_most_of_page(page, bbox) for bbox in _image_bboxes(page))

    if has_native_text and not has_large_image:
        return "native"
    if has_large_image and not has_native_text:
        return "scanned"
    if has_large_image and has_native_text:
        return "hybrid"
    return "unknown"


def _image_bboxes(page: fitz.Page) -> list[fitz.Rect]:
    bboxes: list[fitz.Rect] = []
    try:
        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            if bbox:
                bboxes.append(fitz.Rect(bbox))
    except Exception:
        return []
    return bboxes


def img_bbox_covers_most_of_page(page: fitz.Page, bbox: fitz.Rect, threshold: float = 0.60) -> bool:
    page_area = max(page.rect.get_area(), 1.0)
    overlap = fitz.Rect(bbox) & page.rect
    if overlap.is_empty:
        return False
    return overlap.get_area() / page_area >= threshold

