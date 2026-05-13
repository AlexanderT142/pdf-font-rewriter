from __future__ import annotations

import fitz

from .models import TextLine


def remove_safe_text(page: fitz.Page, safe_lines: list[TextLine]) -> None:
    if not safe_lines:
        return

    original_links = list(page.get_links())

    for line in safe_lines:
        for run in line.runs:
            rect = fitz.Rect(run.bbox) + (-0.5, -0.5, 0.5, 0.5)
            _add_redaction_without_fill(page, rect)

    page.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )

    _restore_links(page, original_links)


def _add_redaction_without_fill(page: fitz.Page, rect: fitz.Rect) -> None:
    try:
        page.add_redact_annot(rect, fill=False)
    except TypeError:
        page.add_redact_annot(rect, fill=None)


def _restore_links(page: fitz.Page, original_links: list[dict]) -> None:
    current_links = list(page.get_links())
    for link in original_links:
        if _same_link_exists(link, current_links):
            continue
        restored = dict(link)
        restored.pop("xref", None)
        try:
            page.insert_link(restored)
        except Exception:
            continue


def _same_link_exists(candidate: dict, links: list[dict]) -> bool:
    candidate_cmp = _link_without_xref(candidate)
    return any(_link_without_xref(link) == candidate_cmp for link in links)


def _link_without_xref(link: dict) -> dict:
    clean = dict(link)
    clean.pop("xref", None)
    return clean

