"""2.3.0 polish (Kyle, 2026-10-31): letters whose signature would end up alone on page 2.

Donation receipts, year-end statements and payment cover letters are laid out the same way:

1. **Fit to one page when it's close.** A letter that lays out on two pages is tried again with tighter spacing
   between sections, then 0.5 pt and 1 pt smaller type (never below 8 pt). The first that fits on one page is used.
2. **The signature never stands alone.** The letter's last paragraph goes with the closing and signature (all kept
   together), so a second page starts with the end of the letter, not a lone signature.
3. **A continuation header on later pages:** "<organization> · <document> · Page 2 of 2", so separated pages stay
   identifiable. Page 1 carries "Continued on page 2" at the bottom.

`FixedSpacer` marks space that must not shrink: the window-envelope layout, pre-printed letterhead, and the room to
sign by hand.
"""
from __future__ import annotations

from typing import Callable

from reportlab.platypus import KeepTogether, Paragraph, Spacer

MIN_SIZE = 8.0
# (spacing factor, type size change): the normal layout first, then tighter spacing, then smaller type
TRIES = ((1.0, 0.0), (0.6, 0.0), (0.6, -0.5), (0.6, -1.0))
HEADER_GREY = 0.4


class FixedSpacer(Spacer):
    """Space that keeps its height when a letter is fitted to one page."""


def scale_spacers(flowables: list, factor: float) -> list:
    """The flowables with every ordinary Spacer's height scaled (inside KeepTogether too); FixedSpacer untouched."""
    if factor == 1.0:
        return flowables
    out = []
    for f in flowables:
        if isinstance(f, Spacer) and not isinstance(f, FixedSpacer):
            out.append(Spacer(f.width, f.height * factor))
        elif isinstance(f, KeepTogether):
            out.append(KeepTogether(scale_spacers(list(f._content), factor), maxHeight=f._maxHeight))
        else:
            out.append(f)
    return out


def with_tail(body: list, closing_block: list) -> list:
    """The body with its last paragraph moved into the closing block, the whole block kept together. A last
    KeepTogether (the acknowledgment block) gives up only its own last paragraph; a table stays where it is."""
    body = list(body)
    while body and isinstance(body[-1], Spacer):
        body.pop()
    if not closing_block:
        return body
    tail: list = []
    if body and isinstance(body[-1], Paragraph):
        tail = [body.pop()]
    elif body and isinstance(body[-1], KeepTogether):
        inner = list(body[-1]._content)
        if len(inner) > 1 and isinstance(inner[-1], Paragraph):
            para = inner.pop()
            gap = inner.pop() if inner and isinstance(inner[-1], Spacer) else None
            body[-1] = KeepTogether(inner)
            tail = ([gap] if gap is not None else []) + [para]
    return body + [KeepTogether(tail + closing_block)]


def sizes_for(size: float) -> list[tuple[float, float]]:
    return [(sp, size + dz) for sp, dz in TRIES if dz == 0 or size + dz >= MIN_SIZE]


def fit(build: Callable[[float, float, int], tuple[bytes, int]], size: float, skip_pages: int = 0) -> bytes:
    """`build(spacing, size, total)` lays the letter out and returns (pdf, pages); `total` > 1 draws the continuation
    header and footer for that many letter pages (0: none). `skip_pages`: leading pages that aren't the letter (the
    address-only page for a double-window envelope)."""
    tries = sizes_for(size)
    pdf, pages = build(tries[0][0], tries[0][1], 0)
    letter_pages = pages - skip_pages
    if letter_pages == 2:
        for sp, sz in tries[1:]:
            p2, n2 = build(sp, sz, 0)
            if n2 - skip_pages == 1:
                return p2
    if letter_pages > 1:
        pdf, _n = build(tries[0][0], tries[0][1], letter_pages)
    return pdf


def draw_continuation(c, page_no: int, total: int, label: str, font: str, skip_pages: int = 0) -> None:
    """Page 1 of the letter: "Continued on page 2" at the bottom; later pages: the header at the top left."""
    n = page_no - skip_pages
    if total <= 1 or n < 1:
        return
    c.saveState()
    c.setFillGray(HEADER_GREY)
    c.setFont(font, 8.5)
    if n == 1:
        c.drawRightString(7.5 * 72, 0.6 * 72, "Continued on page 2")
    else:
        text = f"{label} · Page {n} of {total}"
        while c.stringWidth(text, font, 8.5) > 5.4 * 72 and len(label) > 10:   # clear of the CORRECTED mark
            label = label[:-2].rstrip() + "…"
            text = f"{label} · Page {n} of {total}"
        c.drawString(1.0 * 72, 10.55 * 72, text)
    c.restoreState()
