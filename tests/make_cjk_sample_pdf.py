from __future__ import annotations

import sys
from pathlib import Path

import fitz


BODY_CJK = [
    "社会系统理论是一种关于现代社会的综合性理论。",
    "它把社会描述为由沟通构成的自我再生产系统。",
    "每一次沟通都连接着先前的沟通并开启后续的沟通。",
    "系统与环境的区分是这一理论的基本出发点。",
    "意义是心理系统与社会系统共同使用的媒介。",
]

BODY_MIXED = [
    "Luhmann 在 1984 年出版了 Soziale Systeme 一书。",
    "系统理论中的 autopoiesis 概念借自生物学研究。",
    "所谓 double contingency 指双重偶联性的问题。",
]


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cjk_sample.pdf")
    doc = fitz.open()
    page = doc.new_page(width=420, height=595)
    page.insert_text((60, 70), "社会系统", fontsize=18, fontname="china-s")
    y = 110.0
    for line in BODY_CJK:
        page.insert_text((60, y), line, fontsize=11, fontname="china-s")
        y += 18
    y += 14
    for line in BODY_MIXED:
        page.insert_text((60, y), line, fontsize=11, fontname="china-s")
        y += 18
    page.insert_text((200, 560), "37", fontsize=9, fontname="china-s")
    doc.save(output)
    doc.close()


if __name__ == "__main__":
    main()
