"""Find furigana (ruby) and attach it to the Kanji it reads (spec D9).

Ruby is small kana set right next to its base text: above it in horizontal
text, to its right in vertical text. This is a heuristic; ruby that does
not sit clearly beside larger text is left as ordinary text.
"""

from __future__ import annotations

from .model import Line
from .scripts import is_han, is_kana

RUBY_MAX_RATIO = 0.65


def _is_ruby_text(line: Line) -> bool:
    chars = [c.c for c in line.chars if not c.c.isspace()]
    return bool(chars) and all(is_kana(c) or c == "ー" for c in chars)


def _find_base(ruby: Line, bases: list[Line]):
    rx0, ry0, rx1, ry1 = ruby.bbox
    rs = ruby.size
    best, best_d = None, None
    for base in bases:
        bs = base.size
        if rs > RUBY_MAX_RATIO * bs:
            continue
        bx0, by0, bx1, by1 = base.bbox
        if base.dir == "v":
            overlap = min(ry1, by1) - max(ry0, by0)
            dist = rx0 - bx1
            if overlap > 0 and -0.3 * bs <= dist <= 0.6 * bs:
                if best_d is None or abs(dist) < best_d:
                    best, best_d = base, abs(dist)
        else:
            overlap = min(rx1, bx1) - max(rx0, bx0)
            dist = by0 - ry1
            if overlap > 0 and -0.3 * bs <= dist <= 0.6 * bs:
                if best_d is None or abs(dist) < best_d:
                    best, best_d = base, abs(dist)
    return best


def attach(lines: list[Line], mode: str = "brackets") -> tuple[list[Line], int]:
    """Remove ruby lines, recording their reading on the base line.

    Returns the remaining lines and how many ruby groups were matched.
    With ``mode="drop"`` the readings are discarded.
    """
    candidates = [ln for ln in lines if _is_ruby_text(ln)]
    if not candidates:
        return lines, 0
    # A kana-only line can itself be base text for smaller kana, so every
    # line is a possible base; _find_base checks the size ratio.
    matched: set[int] = set()
    count = 0
    for ruby in candidates:
        base = _find_base(ruby, [ln for ln in lines if ln is not ruby and id(ln) not in matched])
        if base is None:
            continue
        rx0, ry0, rx1, ry1 = ruby.bbox
        pad = 0.3 * base.size
        if base.dir == "v":
            hits = [i for i, c in enumerate(base.chars) if ry0 - pad <= c.cy <= ry1 + pad]
        else:
            hits = [i for i, c in enumerate(base.chars) if rx0 - pad <= c.cx <= rx1 + pad]
        if not hits:
            continue
        han = [i for i in hits if is_han(base.chars[i].c)]
        idx = (han or hits)[-1]
        if mode != "drop":
            base.ruby.append((idx, "".join(c.c for c in ruby.chars if not c.c.isspace())))
        matched.add(id(ruby))
        count += 1
    return [ln for ln in lines if id(ln) not in matched], count
