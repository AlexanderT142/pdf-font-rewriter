"""Diagnostic probe for the socialsystem 2-page test."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refont.classifier import classify_page, _image_bboxes, img_bbox_covers_most_of_page
from refont.extractor import extract_page_index, extract_text_runs
from refont.safety import analyze_page_safety, _safe_bboxlog
from refont.font_utils import build_font_chain


PDF = Path("/Users/tianchenhao/projects/pdffont/artifacts/socialsystem-scan-test/socialsystem_middle_2pages.pdf")
FONT = Path("/System/Library/Fonts/Supplemental/Georgia.ttf")


def describe_image_bboxes(page: fitz.Page) -> list[dict]:
    out: list[dict] = []
    page_area = max(page.rect.get_area(), 1.0)
    for bbox in _image_bboxes(page):
        overlap = fitz.Rect(bbox) & page.rect
        coverage = (overlap.get_area() / page_area) if not overlap.is_empty else 0.0
        out.append({
            "bbox": tuple(bbox),
            "coverage": coverage,
            "covers_most": img_bbox_covers_most_of_page(page, bbox),
        })
    return out


def native_text_present(page: fitz.Page) -> tuple[bool, int]:
    text_dict = page.get_text("dict")
    span_count = 0
    has_text = False
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_count += 1
                if span.get("text", "").strip():
                    has_text = True
    return has_text, span_count


def first_rawdict_blocks(page: fitz.Page, n: int = 3) -> list[dict]:
    raw = page.get_text("rawdict")
    blocks = [b for b in raw.get("blocks", []) if b.get("type") == 0]
    summary = []
    for block in blocks[:n]:
        line_summaries = []
        for line in block.get("lines", [])[:2]:
            for span in line.get("spans", [])[:2]:
                text = span.get("text") or "".join(c.get("c", "") for c in span.get("chars", []))
                line_summaries.append({
                    "text_repr": repr(text[:80]),
                    "font": span.get("font"),
                    "size": span.get("size"),
                    "bbox": span.get("bbox"),
                    "chars_count": len(span.get("chars", [])),
                })
        summary.append({
            "bbox": block.get("bbox"),
            "spans": line_summaries,
        })
    return summary


def bboxlog_summary(page: fitz.Page) -> tuple[Counter, list]:
    try:
        raw = page.get_bboxlog()
    except Exception as exc:
        return Counter(), [("error", str(exc))]
    types = Counter()
    samples = []
    for entry in raw:
        if isinstance(entry, (tuple, list)) and entry:
            etype = str(entry[0])
            types[etype] += 1
            if len(samples) < 5:
                samples.append(entry)
    return types, samples


def texttrace_spans(page: fitz.Page, n: int = 5) -> list[dict]:
    try:
        traces = page.get_texttrace()
    except Exception as exc:
        return [{"error": str(exc)}]
    out = []
    for span in traces[:n]:
        chars = span.get("chars", [])
        text_chars = []
        for c in chars[:20]:
            if isinstance(c, dict):
                text_chars.append(c.get("c") or c.get("text"))
            elif isinstance(c, (tuple, list)) and c:
                val = c[0]
                if isinstance(val, int):
                    try:
                        text_chars.append(chr(val))
                    except Exception:
                        text_chars.append(f"<{val}>")
                else:
                    text_chars.append(str(val))
        out.append({
            "type": span.get("type"),
            "render_mode": span.get("render_mode") or span.get("type"),
            "opacity": span.get("opacity"),
            "font": span.get("font"),
            "size": span.get("size"),
            "wmode": span.get("wmode"),
            "dir": span.get("dir"),
            "bbox": span.get("bbox"),
            "char_count": len(chars),
            "sample_text": "".join(c for c in text_chars if isinstance(c, str))[:60],
        })
    return out


def texttrace_render_mode_counts(page: fitz.Page) -> Counter:
    try:
        traces = page.get_texttrace()
    except Exception:
        return Counter()
    counter = Counter()
    for span in traces:
        rm = span.get("type")
        counter[rm] += 1
    return counter


def page_diagnostic(page: fitz.Page, page_no: int, font_chain) -> None:
    print(f"\n{'='*70}")
    print(f"## Page {page_no + 1} Diagnostic")
    print(f"{'='*70}")
    print(f"Page rect: {page.rect}, rotation: {page.rotation}")

    # Classification
    has_text, span_total = native_text_present(page)
    img_info = describe_image_bboxes(page)
    classification = classify_page(page)
    print(f"\n[Classification]")
    print(f"  has_native_text: {has_text}  (total spans in dict: {span_total})")
    print(f"  images: {len(img_info)}")
    for i, info in enumerate(img_info[:5]):
        print(f"    image[{i}]: coverage={info['coverage']:.3f} covers_most={info['covers_most']}")
    print(f"  -> classification: {classification}")

    # rawdict sample
    print(f"\n[Text extraction (rawdict, first 3 blocks)]")
    for i, block in enumerate(first_rawdict_blocks(page, 3)):
        print(f"  block[{i}] bbox={block['bbox']}")
        for j, s in enumerate(block["spans"]):
            print(f"    span[{j}] font={s['font']} size={s['size']} text={s['text_repr']} chars={s['chars_count']}")

    # texttrace
    print(f"\n[get_texttrace, first 5 spans]")
    for i, span in enumerate(texttrace_spans(page, 5)):
        print(f"  span[{i}]: {span}")
    rm_counts = texttrace_render_mode_counts(page)
    print(f"  texttrace span 'type' field counts (render mode): {dict(rm_counts)}")

    # bboxlog
    print(f"\n[get_bboxlog summary]")
    types, samples = bboxlog_summary(page)
    print(f"  counts by type: {dict(types)}")
    for i, s in enumerate(samples):
        print(f"  sample[{i}]: {s}")

    # extractor + safety
    page_index = extract_page_index(page, page_no, classification)
    analyze_page_safety(page, page_index, font_chain, "conservative")
    print(f"\n[Extractor results]")
    print(f"  lines extracted: {len(page_index.lines)}")
    for i, line in enumerate(page_index.lines[:3]):
        print(f"  line[{i}]: dir={line.direction} text={line.text[:80]!r} safety={line.safety}")
        if line.unsafe_reasons:
            print(f"    unsafe_reasons: {line.unsafe_reasons}")
    print(f"\n[Safety summary]")
    print(f"  safe_lines: {page_index.safe_line_count}")
    print(f"  unsafe_lines: {page_index.unsafe_line_count}")
    reason_counts: Counter = Counter()
    for line in page_index.lines:
        for r in line.unsafe_reasons:
            reason_counts[r] += 1
    print(f"  unsafe reasons aggregate: {dict(reason_counts)}")


def main() -> None:
    print(f"PDF: {PDF}")
    print(f"Exists: {PDF.exists()}, size: {PDF.stat().st_size if PDF.exists() else 'N/A'}")
    doc = fitz.open(PDF)
    print(f"Page count: {doc.page_count}")
    font_chain = build_font_chain(FONT, None)
    for i in range(doc.page_count):
        page_diagnostic(doc[i], i, font_chain)
    doc.close()


if __name__ == "__main__":
    main()
