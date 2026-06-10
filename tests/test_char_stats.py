"""Regression check for _char_visual_stats sampler plumbing.

Guards against the bug where per-char heights were never appended to
nonspace_heights, leaving nonspace_count at 0 and measured_ink stuck at
False — which silently disabled the trusted (sampled-ink) metric windows.

Run: .venv/bin/python tests/test_char_stats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz

from refont.classifier import classify_page
from refont.extractor import extract_page_index
from refont.ink_sampler import PageInkSampler
from refont.visual_fit import _char_visual_stats, _line_chars


def main() -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((50, 100), "measure these common lowercase words", fontsize=11, fontname="helv")

    sampler = PageInkSampler(page)
    page_index = extract_page_index(page, 0, classify_page(page))
    lines = [line for line in page_index.lines if line.text.strip()]
    assert len(lines) == 1, f"expected 1 line, got {len(lines)}"
    line = lines[0]
    chars = [char for char in _line_chars(line) if char.char.strip()]
    assert chars, "extraction produced no chars"

    stats = _char_visual_stats(chars, line, sampler)
    assert stats.nonspace_count > 0, f"nonspace_count is {stats.nonspace_count}, heights not collected"
    assert stats.nonspace_count == len(chars), (
        f"every non-space char must contribute: {stats.nonspace_count} != {len(chars)}"
    )
    assert stats.measured_ink, "sampler measured the line but measured_ink is False"
    # Sampled ink heights must be real ink, not font boxes (== font size).
    assert stats.nonspace_height_pt < 11 * 0.9, (
        f"nonspace_height_pt {stats.nonspace_height_pt:.2f} looks like a font box, not ink"
    )
    assert stats.lower_mid_height_pt and stats.lower_mid_height_pt < 11 * 0.7, (
        f"lower_mid_height_pt {stats.lower_mid_height_pt} is not a plausible x-height"
    )

    # Without a sampler, heights come from font boxes and must NOT be trusted.
    stats_no_sampler = _char_visual_stats(chars, line, None)
    assert stats_no_sampler.nonspace_count == len(chars)
    assert not stats_no_sampler.measured_ink, "measured_ink must be False without a sampler"

    doc.close()
    print(
        "OK: nonspace_count="
        f"{stats.nonspace_count}, measured_ink={stats.measured_ink}, "
        f"x-height={stats.lower_mid_height_pt:.2f}pt, nonspace={stats.nonspace_height_pt:.2f}pt"
    )


if __name__ == "__main__":
    main()
