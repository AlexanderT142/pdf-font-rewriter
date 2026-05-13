from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from .classifier import classify_page
from .extractor import extract_page_index
from .font_utils import build_font_chain
from .inserter import insert_replacement_text
from .models import PageIndex, TextLine
from .remover import remove_safe_text
from .report import write_json_report
from .safety import analyze_page_safety


@dataclass(frozen=True)
class ConversionOptions:
    input_pdf: Path
    target_font: Path
    output_pdf: Path | None
    report_path: Path
    cjk_fallback: Path | None = None
    mode: str = "conservative"
    pages: set[int] | None = None
    dry_run: bool = False
    verbose: bool = False


def rewrite_pdf(options: ConversionOptions) -> tuple[list[PageIndex], dict]:
    font_chain = build_font_chain(options.target_font, options.cjk_fallback)
    doc = fitz.open(options.input_pdf)
    page_indexes: list[PageIndex] = []

    try:
        for page_no in range(doc.page_count):
            page = doc[page_no]
            if options.pages is not None and page_no not in options.pages:
                page_index = PageIndex(
                    page_no=page_no,
                    width_pt=float(page.rect.width),
                    height_pt=float(page.rect.height),
                    rotation=int(page.rotation),
                    classification="not_selected",
                )
                page_indexes.append(page_index)
                continue

            classification = classify_page(page)
            page_index = extract_page_index(page, page_no, classification)
            analyze_page_safety(page, page_index, font_chain, options.mode)
            page_indexes.append(page_index)

            if options.verbose:
                print(
                    f"page {page_no + 1}: {classification}, "
                    f"safe={page_index.safe_line_count}, unsafe={page_index.unsafe_line_count}"
                )

            if not options.dry_run and page_index.classification in {"native", "hybrid"}:
                _rewrite_page(page, page_index)

        if not options.dry_run:
            if not options.output_pdf:
                raise ValueError("output path is required unless dry-run is enabled")
            options.output_pdf.parent.mkdir(parents=True, exist_ok=True)
            doc.save(options.output_pdf, garbage=4, deflate=True)
    finally:
        doc.close()

    report = write_json_report(
        options.report_path,
        options.input_pdf,
        None if options.dry_run else options.output_pdf,
        options.target_font,
        page_indexes,
        options.dry_run,
    )
    return page_indexes, report


def _rewrite_page(page: fitz.Page, page_index: PageIndex) -> None:
    safe_lines = _safe_lines(page_index)
    if not safe_lines:
        return
    remove_safe_text(page, safe_lines)
    insert_replacement_text(page, safe_lines)


def _safe_lines(page_index: PageIndex) -> list[TextLine]:
    return [line for line in page_index.lines if line.safety == "safe"]
