"""Read characters from a PDF page and rebuild lines and vertical columns.

PDF producers rarely store vertical text as vertical lines. LibreOffice,
InDesign and Word export vertical CJK as many short horizontal fragments,
often one character each, stacked down the page. So direction is decided
from where the characters actually sit, not from the line metadata.
"""

from __future__ import annotations

import unicodedata

import pymupdf

from .cmaps import needs_cid_text
from .model import Char, Line


def page_chars(page) -> list[list[Char]]:
    """Characters of each line MuPDF found, with their boxes and fonts.

    Characters of rotated lines (Latin letters and digits turned sideways
    inside vertical text) are marked so columns can take them in.
    """
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_MEDIABOX_CLIP
    if needs_cid_text(page):
        flags |= pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE
    raw = page.get_text("rawdict", flags=flags)
    fragments: list[list[Char]] = []
    for block in raw["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            chars: list[Char] = []
            rotated = abs(line["dir"][1]) > abs(line["dir"][0])
            for span in line["spans"]:
                bold = bool(span["flags"] & 16) or "bold" in span["font"].lower()
                for ch in span["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    if x1 - x0 <= 0 and y1 - y0 <= 0:
                        continue
                    # Fonts in vertical writing mode (Identity-V, Uni*-V) give
                    # every glyph a vertical direction; only narrow ones
                    # (Latin, digits) are actually turned sideways.
                    sideways = rotated and unicodedata.east_asian_width(ch["c"][:1] or " ") not in "WF"
                    # Some producers give vertical glyphs a zero-width box at
                    # the column's right edge; give it a square footprint.
                    # A sideways glyph's length down the column is its advance,
                    # which is short for a comma or a period: keep it.
                    if x1 - x0 < 0.2 * (y1 - y0):
                        x0 = x1 - 0.9 * (y1 - y0)
                    elif y1 - y0 < 0.2 * (x1 - x0) and not sideways:
                        y0 = y1 - 0.9 * (x1 - x0)
                    chars.append(Char(ch["c"], x0, y0, x1, y1, span["size"], span["font"], bold, sideways))
            if chars:
                fragments.append(chars)
    return fragments


def _classify(chars: list[Char]) -> str:
    """'h', 'v', or '?' (a single character or nothing to go on)."""
    visible = [c for c in chars if not c.c.isspace()]
    if len(visible) < 2:
        return "?"
    dx = visible[-1].cx - visible[0].cx
    dy = visible[-1].cy - visible[0].cy
    return "v" if abs(dy) > abs(dx) else "h"


def _is_punct(c: str) -> bool:
    return unicodedata.category(c[:1] or " ").startswith("P")


def _cell_top(ch: Char) -> float:
    """Where a character's cell starts down a column. Some producers
    (ReportLab) draw full-width punctuation shifted up into the cell
    before it, so its box starts above its own cell."""
    if _is_punct(ch.c) and not ch.rotated and unicodedata.east_asian_width(ch.c[:1]) in "WF":
        return ch.y0 + 0.5 * ch.size
    return ch.y0


def _similar(a: float, b: float) -> bool:
    return 0.8 <= a / b <= 1.25 if b else False


def build_lines(fragments: list[list[Char]], forced: str | None = None) -> list[Line]:
    """Join fragments into horizontal lines and vertical columns.

    ``forced`` is the owner's direction choice. With "h", single characters
    are never stacked into columns; real vertical fragments still are,
    because their geometry is unambiguous.
    """
    horizontal: list[Line] = []
    stackable: list[tuple[str, list[Char]]] = []
    for chars in fragments:
        kind = _classify(chars)
        visible = [c for c in chars if not c.c.isspace()]
        upright_in_column = (kind == "h" and forced != "h" and len(visible) <= 4
                             and max(c.x1 for c in chars) - min(c.x0 for c in chars) <= 1.3 * max(c.size for c in chars))
        if upright_in_column:
            # A few narrow letters or digits set across a column
            # (tate-chu-yoko); kept horizontal unless it stacks with a column.
            stackable.append(("h", chars))
        elif kind == "h" or (kind == "?" and forced == "h"):
            horizontal.append(Line(sorted(chars, key=lambda c: c.x0), "h"))
        else:
            # MuPDF lists a line's characters in reading order; sorting by
            # position would let a wide sideways box (a space, a comma)
            # jump ahead of the letter it follows.
            if chars[0].cy > chars[-1].cy:
                chars = chars[::-1]
            stackable.append((kind, chars))

    # Chain stacked fragments into columns, top to bottom.
    stackable.sort(key=lambda kc: (_cell_top(kc[1][0]), -kc[1][0].cx))
    columns: list[list[Char]] = []
    open_cols: list[list[Char]] = []
    # The fragments of columns made only of short horizontal pieces; they
    # stay horizontal unless a real vertical fragment joins them.
    only_h: dict[int, list[list[Char]]] = {}
    for kind, chars in stackable:
        head = chars[0]
        best, best_d = None, None
        for col in open_cols:
            tail = col[-1]
            gap = head.y0 - tail.y1
            # Full-width punctuation is drawn in the upper right of its cell,
            # so the next character can start most of a cell after its box.
            # Punctuation pairs such as "），" may overlap.
            # Fonts with a tall ascent and descent give taller boxes that
            # overlap more.
            punct = _is_punct(tail.c)
            overlap = (0.6 if punct or _is_punct(head.c) else 0.3) * max(tail.size, tail.y1 - tail.y0)
            room = 1.0 if punct else 0.6
            if not (-overlap <= gap <= room * tail.size and _similar(head.size, tail.size)):
                continue
            # Sideways glyphs sit off the column's centre line, sometimes
            # beside it, so for them the boxes only need to come close.
            # Take the nearest column in reach, not the first one.
            size = max(tail.size, head.size)
            centre = abs(head.cx - tail.cx)
            if head.rotated or tail.rotated:
                apart = max(head.x0, tail.x0) - min(head.x1, tail.x1)
                if apart > 0.6 * size:
                    continue
                d = (max(apart, 0), centre)
            elif centre <= 0.35 * size:
                d = (0, centre)
            else:
                continue
            if best_d is None or d < best_d:
                best, best_d = col, d
        if best is None:
            best = []
            open_cols.append(best)
            columns.append(best)
            if kind == "h":
                only_h[id(best)] = []
        if id(best) in only_h:
            if kind == "h":
                only_h[id(best)].append(chars)
            else:
                del only_h[id(best)]
        best.extend(chars)

    lines = horizontal
    singles: list[Char] = []
    for col in columns:
        if id(col) in only_h:
            lines.extend(Line(sorted(f, key=lambda c: c.x0), "h") for f in only_h[id(col)])
        elif len([c for c in col if not c.c.isspace()]) >= 2:
            lines.append(Line(col, "v"))
        else:
            singles.extend(col)
    # Characters that stacked with nothing are short horizontal pieces
    # (a page number, a lone punctuation mark); join neighbours on a row.
    singles.sort(key=lambda c: (round(c.cy / max(c.size, 1)), c.x0))
    row: list[Char] = []
    for ch in singles:
        if row and (abs(ch.cy - row[-1].cy) > 0.5 * ch.size or ch.x0 - row[-1].x1 > 0.8 * ch.size):
            lines.append(Line(row, "h"))
            row = []
        row.append(ch)
    if row:
        lines.append(Line(row, "h"))
    return [ln for ln in lines if ln.text.strip()]
