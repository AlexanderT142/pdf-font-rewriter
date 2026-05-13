from __future__ import annotations

import argparse
from pathlib import Path

from .converter import ConversionOptions, rewrite_pdf
from .report import print_summary


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_pdf = Path(args.input_pdf).expanduser().resolve()
    target_font = Path(args.font).expanduser().resolve()
    if not input_pdf.exists():
        parser.error(f"input PDF not found: {input_pdf}")
    if not target_font.exists():
        parser.error(f"target font not found: {target_font}")

    output_pdf = Path(args.output).expanduser().resolve() if args.output else default_output_path(input_pdf)
    if not args.dry_run and input_pdf == output_pdf:
        parser.error("output path must be different from input path")

    report_path = Path(args.report).expanduser().resolve() if args.report else default_report_path(output_pdf)
    selected_pages = parse_page_range(args.pages) if args.pages else None
    cjk_fallback = Path(args.cjk_fallback).expanduser().resolve() if args.cjk_fallback else None

    if args.preview:
        print("--preview is accepted for CLI compatibility, but the MVP does not include a browser preview.")

    options = ConversionOptions(
        input_pdf=input_pdf,
        target_font=target_font,
        output_pdf=None if args.dry_run else output_pdf,
        report_path=report_path,
        cjk_fallback=cjk_fallback,
        mode=args.mode,
        pages=selected_pages,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    _, report = rewrite_pdf(options)
    print_summary(report, report_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refont",
        description="Conservatively rewrite native PDF text into a target font.",
    )
    parser.add_argument("input_pdf", help="Input PDF file path")
    parser.add_argument("--font", required=True, help="Target .ttf/.otf font file")
    parser.add_argument("--output", help="Output PDF path (default: INPUT_refonted.pdf)")
    parser.add_argument("--cjk-fallback", help="CJK fallback font file")
    parser.add_argument("--mode", choices=["conservative", "normal"], default="conservative")
    parser.add_argument("--report", help="Audit JSON path (default: alongside output PDF)")
    parser.add_argument("--pages", help='Page range to process, e.g. "1-10,15,20-30"')
    parser.add_argument("--preview", action="store_true", help="Reserved for future before/after preview")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write an output PDF")
    parser.add_argument("--verbose", action="store_true", help="Print per-page details")
    return parser


def default_output_path(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}_refonted.pdf")


def default_report_path(output_pdf: Path) -> Path:
    return output_pdf.with_name(f"{output_pdf.stem}_audit.json")


def parse_page_range(value: str) -> set[int]:
    pages: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            if start <= 0 or end <= 0 or end < start:
                raise argparse.ArgumentTypeError(f"invalid page range: {token}")
            pages.update(range(start - 1, end))
        else:
            page = int(token)
            if page <= 0:
                raise argparse.ArgumentTypeError(f"invalid page number: {token}")
            pages.add(page - 1)
    return pages


if __name__ == "__main__":
    main()

