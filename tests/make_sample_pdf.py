from __future__ import annotations

import sys
from pathlib import Path

import fitz


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample.pdf")
    doc = fitz.open()
    page = doc.new_page(width=420, height=595)
    page.insert_text((72, 90), "PDF Font Rewriter smoke test", fontsize=18, fontname="helv")
    page.insert_text((72, 130), "This native text should be replaceable.", fontsize=12, fontname="helv")
    page.insert_text((72, 156), "Kerning and ligatures: office affinity efficient.", fontsize=12, fontname="helv")
    page.draw_rect(fitz.Rect(70, 175, 330, 235), color=(0.1, 0.3, 0.7), width=1)
    page.insert_text((72, 260), "Safe line after vector graphic.", fontsize=12, fontname="helv")
    doc.save(output)
    doc.close()


if __name__ == "__main__":
    main()

