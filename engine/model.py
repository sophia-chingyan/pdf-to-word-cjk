"""Small geometry types shared by the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass
class Char:
    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    font: str = ""
    bold: bool = False
    rotated: bool = False

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def bbox_of(items) -> tuple[float, float, float, float]:
    xs0, ys0, xs1, ys1 = zip(*((i.x0, i.y0, i.x1, i.y1) for i in items))
    return min(xs0), min(ys0), max(xs1), max(ys1)


@dataclass
class Line:
    """A run of characters in reading order: a horizontal line or a vertical column."""

    chars: list[Char]
    dir: str  # "h" or "v"
    # Furigana attached to this line: (index of the last base character, reading).
    ruby: list[tuple[int, str]] = field(default_factory=list)

    @property
    def bbox(self):
        return bbox_of(self.chars)

    @property
    def x0(self):
        return self.bbox[0]

    @property
    def y0(self):
        return self.bbox[1]

    @property
    def x1(self):
        return self.bbox[2]

    @property
    def y1(self):
        return self.bbox[3]

    @property
    def size(self) -> float:
        return median(c.size for c in self.chars)

    @property
    def text(self) -> str:
        return "".join(c.c for c in self.chars)

    # Coordinates along and across the reading direction, so the layout code
    # can treat columns exactly like lines.
    @property
    def start(self):  # where the line begins along its direction
        return self.x0 if self.dir == "h" else self.y0

    @property
    def end(self):
        return self.x1 if self.dir == "h" else self.y1


@dataclass
class Block:
    lines: list[Line]
    dir: str

    @property
    def bbox(self):
        return bbox_of(self.lines)

    @property
    def size(self) -> float:
        sizes = [c.size for ln in self.lines for c in ln.chars]
        return median(sizes)

    @property
    def text(self) -> str:
        return "".join(ln.text for ln in self.lines)
