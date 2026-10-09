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
                    # Some producers give vertical glyphs a zero-width box at
                    # the column's right edge; give it a square footprint.
                    if x1 - x0 < 0.2 * (y1 - y0):
                        x0 = x1 - 0.9 * (y1 - y0)
                    elif y1 - y0 < 0.2 * (x1 - x0):
                        y0 = y1 - 0.9 * (x1 - x0)
                    # Fonts in vertical writing mode (Identity-V, Uni*-V) give
                    # every glyph a vertical direction; only narrow ones
                    # (Latin, digits) are actually turned sideways.
                    sideways = rotated and unicodedata.east_asian_width(ch["c"][:1] or " ") not in "WF"
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
        if kind == "h" or (kind == "?" and forced == "h"):
            horizontal.append(Line(sorted(chars, key=lambda c: c.x0), "h"))
        else:
            stackable.append((kind, sorted(chars, key=lambda c: c.y0)))

    # Chain stacked fragments into columns, top to bottom.
    stackable.sort(key=lambda kc: (kc[1][0].y0, -kc[1][0].cx))
    columns: list[list[Char]] = []
    open_cols: list[list[Char]] = []
    for _kind, chars in stackable:
        head = chars[0]
        best = None
        for col in open_cols:
            tail = col[-1]
            gap = head.y0 - tail.y1
            size = max(tail.size, head.size)
            if head.rotated or tail.rotated:
                # Sideways glyphs sit off the column's centre line.
                across = max(head.x0, tail.x0) - min(head.x1, tail.x1) <= 0.6 * size
            else:
                across = abs(head.cx - tail.cx) <= 0.35 * size
            if -0.3 * tail.size <= gap <= 0.6 * tail.size and across and _similar(head.size, tail.size):
                best = col
                break
        if best is None:
            best = []
            open_cols.append(best)
            columns.append(best)
        best.extend(chars)

    lines = list(horizontal)
    singles: list[Char] = []
    for col in columns:
        if len([c for c in col if not c.c.isspace()]) >= 2:
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
