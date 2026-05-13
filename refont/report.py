from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .models import PageIndex
from .safety import summarize_unsafe_reasons


def write_json_report(
    path: Path,
    input_file: Path,
    output_file: Path | None,
    target_font: Path,
    page_indexes: list[PageIndex],
    dry_run: bool,
) -> dict:
    report = build_report(input_file, output_file, target_font, page_indexes, dry_run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def build_report(
    input_file: Path,
    output_file: Path | None,
    target_font: Path,
    page_indexes: list[PageIndex],
    dry_run: bool,
) -> dict:
    per_page = [_page_summary(page) for page in page_indexes]
    counted_pages = [page for page in per_page if page["status"] != "not_selected"]
    skipped_reasons = _skipped_reasons(per_page, page_indexes)

    return {
        "input_file": str(input_file),
        "output_file": str(output_file) if output_file else None,
        "target_font": str(target_font),
        "dry_run": dry_run,
        "total_pages": len(page_indexes),
        "pages_fully_converted": sum(1 for page in counted_pages if page["status"] == "fully_converted"),
        "pages_partially_converted": sum(1 for page in counted_pages if page["status"] == "partially_converted"),
        "pages_skipped": sum(1 for page in counted_pages if page["status"] == "skipped"),
        "skipped_reasons": skipped_reasons,
        "per_page": per_page,
    }


def print_summary(report: dict, report_path: Path) -> None:
    total = max(int(report["total_pages"]), 1)
    fully = int(report["pages_fully_converted"])
    partial = int(report["pages_partially_converted"])
    skipped = int(report["pages_skipped"])
    issues = [
        str(page["page"])
        for page in report["per_page"]
        if page["status"] in {"partially_converted", "skipped"} and page["status"] != "not_selected"
    ]

    print("PDF Font Rewriter - Conversion Report")
    print("======================================")
    print(f"Input:  {report['input_file']}")
    if report.get("output_file"):
        print(f"Output: {report['output_file']}")
    else:
        print("Output: dry run only; no PDF written")
    print(f"Font:   {report['target_font']}")
    print(f"Report: {report_path}")
    print()
    print("Results:")
    print(f"  Fully converted:      {fully:5d} pages ({fully / total * 100:.1f}%)")
    print(f"  Partially converted:  {partial:5d} pages")
    print(f"  Skipped:              {skipped:5d} pages")
    print()
    print("Skip reasons:")
    if report["skipped_reasons"]:
        for reason, count in report["skipped_reasons"].items():
            print(f"  {reason}: {count}")
    else:
        print("  none")
    if issues:
        print()
        print(f"Pages with issues: {', '.join(issues)}")


def _page_summary(page: PageIndex) -> dict:
    reasons = summarize_unsafe_reasons(page.lines)
    status = _page_status(page)
    return {
        "page": page.page_no + 1,
        "classification": page.classification,
        "total_lines": len(page.lines),
        "safe_lines": page.safe_line_count,
        "unsafe_lines": page.unsafe_line_count,
        "unsafe_reasons": reasons,
        "visual_roles": _visual_roles(page),
        "region_decisions": page.region_decisions,
        "text_layer_corrections": _text_layer_corrections(page),
        "status": status,
    }


def _page_status(page: PageIndex) -> str:
    if page.classification == "not_selected":
        return "not_selected"
    if page.classification not in {"native", "hybrid"}:
        return "skipped"
    if not page.lines:
        return "skipped"
    if page.safe_line_count == len(page.lines):
        return "fully_converted"
    if page.safe_line_count > 0:
        return "partially_converted"
    return "skipped"


def _skipped_reasons(per_page: list[dict], page_indexes: list[PageIndex]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for summary, page in zip(per_page, page_indexes):
        if summary["status"] == "not_selected":
            continue
        if page.classification == "scanned":
            counter["scanned_or_image_only"] += 1
        elif page.classification == "hybrid" and summary["status"] == "skipped" and not page.lines:
            counter["hybrid_text_over_image"] += 1
        elif page.classification == "unknown":
            counter["unknown_page_type"] += 1
        elif summary["status"] in {"skipped", "partially_converted"}:
            for reason, count in summary["unsafe_reasons"].items():
                counter[reason] += count
    return dict(counter)


def _visual_roles(page: PageIndex) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for line in page.lines:
        if line.fit_result and line.fit_result.visual_decision:
            counter[line.fit_result.visual_decision.role.value] += 1
    return dict(counter)


def _text_layer_corrections(page: PageIndex) -> dict:
    corrections = []
    counter: Counter[str] = Counter()
    for line_index, line in enumerate(page.lines):
        if not line.text_layer_corrections:
            continue
        for correction in line.text_layer_corrections:
            counter[correction.decision] += 1
            corrections.append(
                {
                    "line_index": line_index,
                    "line_text_before": line.original_text or line.text,
                    "line_text_after": line.text,
                    "index": correction.index,
                    "original": correction.original,
                    "replacement": correction.replacement,
                    "confidence": correction.confidence,
                    "decision": correction.decision,
                    "reason": correction.reason,
                    "signals": list(correction.signals),
                    "bbox": list(correction.bbox) if correction.bbox else None,
                    "visual_scores": correction.visual_scores,
                    "context_scores": correction.context_scores,
                }
            )
    return {
        "counts": dict(counter),
        "items": corrections,
    }
