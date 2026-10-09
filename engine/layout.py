"""Group lines into blocks and paragraphs, and put page regions in reading order."""

from __future__ import annotations

import re

from .model import Block, Line

BULLETS = "•●○◦■□◆◇▪▫・‧∙-*–—※"
NUMBERED = re.compile(r"^\s*([0-9０-９]{1,3}[.)．、]|[(（][0-9０-９一二三四五六七八九十]{1,3}[)）]|[①-⑳]|[一二三四五六七八九十]{1,3}、)")


def _overlap(a0, a1, b0, b1) -> float:
    return min(a1, b1) - max(a0, b0)


def group_blocks(lines: list[Line]) -> list[Block]:
    """Group consecutive lines (or columns) of one size and direction into blocks."""
    blocks: list[Block] = []
    for direction in ("h", "v"):
        same = [ln for ln in lines if ln.dir == direction]
        if direction == "h":
            same.sort(key=lambda ln: (ln.y0, ln.x0))
        else:
            same.sort(key=lambda ln: (-ln.x1, ln.y0))
        open_blocks: list[tuple[Block, list[float]]] = []  # block, [x0, y0, x1, y1]
        for ln in same:
            s = ln.size
            best, best_gap = None, None
            for blk, bb in open_blocks:
                last = blk.lines[-1]
                if not 0.8 <= s / last.size <= 1.25:
                    continue
                if direction == "h":
                    gap = ln.y0 - last.y1
                    ov = _overlap(ln.x0, ln.x1, bb[0], bb[2])
                    span = min(ln.x1 - ln.x0, bb[2] - bb[0])
                else:
                    gap = last.x0 - ln.x1
                    ov = _overlap(ln.y0, ln.y1, bb[1], bb[3])
                    span = min(ln.y1 - ln.y0, bb[3] - bb[1])
                if -0.3 * s <= gap <= 1.0 * s and span > 0 and ov >= 0.5 * span:
                    if best_gap is None or gap < best_gap:
                        best, best_gap = (blk, bb), gap
            if best is None:
                blk = Block([ln], direction)
                open_blocks.append((blk, list(ln.bbox)))
                blocks.append(blk)
            else:
                blk, bb = best
                blk.lines.append(ln)
                x0, y0, x1, y1 = ln.bbox
                bb[0], bb[1], bb[2], bb[3] = min(bb[0], x0), min(bb[1], y0), max(bb[2], x1), max(bb[3], y1)
    return blocks


def is_list_start(text: str) -> bool:
    t = text.lstrip(" 　")
    if t[:1] in "-–—*":
        # A dash is a bullet only before a space; "——" is a CJK dash in running text.
        return t[1:2] in (" ", "\u3000")
    return bool(t) and (t[0] in BULLETS and len(t) > 1 or bool(NUMBERED.match(t)))


def _edge(values: list[float], tol: float, low: bool) -> float:
    """The block's margin on one side: the outermost value that two or more
    lines share, so one hanging punctuation mark doesn't move it."""
    ordered = sorted(values, reverse=not low)
    for i, v in enumerate(ordered[:-1]):
        if abs(ordered[i + 1] - v) <= tol:
            return v
    return ordered[0]


def block_edges(block: Block) -> tuple[float, float]:
    """Where the block's lines start and end along the reading direction."""
    tol = 0.3 * block.size
    if len(block.lines) < 3:
        return min(ln.start for ln in block.lines), max(ln.end for ln in block.lines)
    return (_edge([ln.start for ln in block.lines], tol, True),
            _edge([ln.end for ln in block.lines], tol, False))


def is_indented(ln: Line, b_start: float) -> bool:
    return ln.start > b_start + 0.8 * ln.size or ln.text.startswith("　")


def uses_indents(block: Block) -> bool:
    """True when paragraphs in this block open with a first-line indent.
    A short line followed by an unindented one is then a line break inside
    the paragraph, not a new paragraph."""
    b_start, _ = block_edges(block)
    return any(is_indented(ln, b_start) and not is_list_start(ln.text) for ln in block.lines)


def split_paragraphs(block: Block) -> list[list[Line]]:
    """Split a block into paragraphs using short last lines and indents."""
    b_start, b_end = block_edges(block)
    indents = uses_indents(block)
    paragraphs: list[list[Line]] = []
    for i, ln in enumerate(block.lines):
        s = ln.size
        new = i == 0
        if not new:
            prev = block.lines[i - 1]
            if prev.end < b_end - 1.5 * s and not indents:
                new = True
            elif is_indented(ln, b_start):
                new = True
            elif is_list_start(ln.text):
                new = True
        if new:
            paragraphs.append([ln])
        else:
            paragraphs[-1].append(ln)
    return paragraphs


def _gaps(intervals: list[tuple[float, float, int]]):
    """Split sorted intervals where coverage has a gap; returns groups and the smallest gap."""
    intervals = sorted(intervals)
    groups, cur, reach, min_gap = [], [], None, None
    for a, b, idx in intervals:
        if reach is not None and a > reach + 1:
            gap = a - reach
            min_gap = gap if min_gap is None else min(min_gap, gap)
            groups.append(cur)
            cur = []
        cur.append(idx)
        reach = b if reach is None else max(reach, b)
    groups.append(cur)
    return groups, (min_gap or 0)


def reading_order(boxes: list[tuple[float, float, float, float]], vertical: bool) -> list[int]:
    """Recursive XY-cut. Horizontal pages read columns left to right,
    vertical pages right to left; stacked tiers always read top to bottom."""

    def order(ids: list[int]) -> list[int]:
        if len(ids) <= 1:
            return ids
        ygroups, ygap = _gaps([(boxes[i][1], boxes[i][3], i) for i in ids])
        xgroups, xgap = _gaps([(boxes[i][0], boxes[i][2], i) for i in ids])
        if len(xgroups) > 1 and (len(ygroups) == 1 or xgap > ygap):
            xgroups.sort(key=lambda g: min(boxes[i][0] for i in g), reverse=vertical)
            return [i for g in xgroups for i in order(g)]
        if len(ygroups) > 1:
            ygroups.sort(key=lambda g: min(boxes[i][1] for i in g))
            return [i for g in ygroups for i in order(g)]
        if vertical:
            return sorted(ids, key=lambda i: (-boxes[i][2], boxes[i][1]))
        return sorted(ids, key=lambda i: (boxes[i][1], boxes[i][0]))

    return order(list(range(len(boxes))))
