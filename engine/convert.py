"""Turn PDF pages into a neutral page description, then into a Word file.

Each page is analysed on its own and saved as JSON, so a paused or
interrupted job resumes from the next unfinished page (spec FR4).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

from . import furigana
from .cmaps import fix_unicode_cmaps
from .extract import build_lines, page_chars
from .layout import BULLETS, NUMBERED, block_edges, ends_short, group_blocks, reading_order, split_paragraphs
from .model import Line
from .options import Options
from .scripts import is_broken, needs_space

SANS_HINTS = ("gothic", "sans", "hei", "kaku", "gulim", "dotum", "malgun", "arial", "helvetica",
              "yahei", "jhenghei", "黑", "ゴシック", "고딕")
CJK_LATIN_SPACE = re.compile(
    r"(?<=[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]) (?=[A-Za-z0-9])|(?<=[A-Za-z0-9]) (?=[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff])"
)
MAX_PAGES = 100
MAX_BYTES = 40 * 1024 * 1024


class ConversionError(Exception):
    """A problem with the input file that the owner should see as-is."""


def open_pdf(path: str | Path, password: str | None = None):
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # MuPDF raises several types for damaged files
        raise ConversionError("檔案不是有效的 PDF，或已損毀。") from exc
    if not doc.is_pdf:
        raise ConversionError("檔案不是 PDF。")
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            raise ConversionError("needs_password")
    fix_unicode_cmaps(doc)
    return doc


def _is_page_number(text: str) -> bool:
    t = text.strip().strip("-–—·．. ")
    return 0 < len(t) <= 4 and (t.isdigit() or t.lower().strip("ivxlc") == "")


def _runs(lines: list[Line]) -> list[list]:
    """Paragraph text as [text, bold] runs, with ruby readings in brackets."""
    runs: list[list] = []

    def put(text: str, bold: bool):
        if not text:
            return
        if runs and runs[-1][1] == bold:
            runs[-1][0] += text
        else:
            runs.append([text, bold])

    prev_text = ""
    for n, ln in enumerate(lines):
        ruby = {}
        for idx, reading in ln.ruby:
            ruby[idx] = ruby.get(idx, "") + reading
        chars = ln.chars
        text = ln.text
        if n:
            if prev_text.endswith("-") and text[:1].isalpha() and prev_text[-2:-1].isalpha():
                # "hyphen-\nated" -> "hyphenated"
                if runs and runs[-1][0].endswith("-"):
                    runs[-1][0] = runs[-1][0][:-1]
            elif needs_space(prev_text, text):
                put(" ", False)
        for i, ch in enumerate(chars):
            put(ch.c, ch.bold)
            if i in ruby:
                put(f"({ruby[i]})", ch.bold)
        prev_text = text
    # MuPDF turns the extra gap that CJK typesetting leaves around Latin
    # letters and digits into a space; Word adds that gap by itself.
    for r in runs:
        r[0] = CJK_LATIN_SPACE.sub("", r[0])
    # Trim spaces at the ends, keep the ideographic indent.
    if runs:
        runs[0][0] = runs[0][0].lstrip(" ")
        runs[-1][0] = runs[-1][0].rstrip()
    return [r for r in runs if r[0]]


def _list_kind(text: str) -> str | None:
    t = text.lstrip(" 　")
    if t[:1] in BULLETS and len(t) > 1 and t[:1] not in "-–—*" or t[:2] in ("- ", "* "):
        return "bullet"
    if NUMBERED.match(t):
        return "number"
    return None


def _image_png(doc, xref: int) -> bytes | None:
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4 or pix.colorspace is None or pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return pix.tobytes("png")
    except Exception:
        return None


def analyze_page(doc, index: int, options: Options, workdir: Path) -> dict:
    """Describe one page as JSON-ready data; images are written to ``workdir``."""
    page = doc[index]
    w, h = page.rect.width, page.rect.height
    warnings: list[str] = []
    forced = options.forced_direction

    # Tables first, so their text is not read twice.
    tables = []
    try:
        if len(page.get_drawings()) >= 4:
            for t in page.find_tables().tables:
                rows = t.extract()
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    tables.append({"bbox": list(t.bbox), "rows": [[(c or "").strip() for c in r] for r in rows]})
    except Exception:
        tables = []

    fragments = page_chars(page)
    if tables:
        def outside(ch):
            return not any(t["bbox"][0] <= ch.cx <= t["bbox"][2] and t["bbox"][1] <= ch.cy <= t["bbox"][3]
                           for t in tables)
        fragments = [f for f in ([c for c in frag if outside(c)] for frag in fragments) if f]

    all_chars = [c for f in fragments for c in f]
    visible = [c for c in all_chars if not c.c.isspace()]
    if visible and sum(is_broken(c.c) for c in visible) > 0.2 * len(visible):
        warnings.append(f"第 {index + 1} 頁：部分字型無法解碼，文字可能有誤，可改用商業服務轉換。")

    lines = build_lines(fragments, forced)
    ruby_count = 0
    if options.auto or "ja-JP" in options.languages:
        lines, ruby_count = furigana.attach(lines, options.furigana)

    blocks = group_blocks(lines)
    blocks = [b for b in blocks
              if not (_is_page_number(b.text) and (b.bbox[1] > 0.9 * h or b.bbox[3] < 0.1 * h))]

    v_chars = sum(len(ln.chars) for b in blocks if b.dir == "v" for ln in b.lines)
    h_chars = sum(len(ln.chars) for b in blocks if b.dir == "h" for ln in b.lines)
    page_dir = forced or ("v" if v_chars > h_chars else "h")

    regions: list[dict] = []
    for b in blocks:
        paragraphs = []
        b_start, b_end = block_edges(b)
        for para in split_paragraphs(b):
            runs = _runs(para)
            text = "".join(r[0] for r in runs)
            if not text.strip():
                continue
            paragraphs.append({
                "runs": runs,
                "size": round(sum(ln.size for ln in para) / len(para), 1),
                "list": _list_kind(text),
                "chars": len(text),
                # Used to rejoin a paragraph that runs on into the next
                # column or page: it fills its last line and the next one
                # starts flush, without an indent.
                "open_end": len(b.lines) > 1 and not ends_short(para[-1], b_end),
                "indent": para[0].text.startswith(("\u3000", " "))
                or para[0].start > b_start + 0.8 * para[0].size,
            })
        if not paragraphs:
            continue
        fonts = Counter(c.font.lower() for ln in b.lines for c in ln.chars)
        top_font = fonts.most_common(1)[0][0] if fonts else ""
        regions.append({
            "type": "text",
            "dir": forced or b.dir,
            "bbox": list(b.bbox),
            "paragraphs": paragraphs,
            "sans": any(k in top_font for k in SANS_HINTS),
            "text": "".join(r[0] for p in paragraphs for r in p["runs"]),
        })

    has_text = bool(regions)
    for n, info in enumerate(page.get_image_info(xrefs=True)):
        x0, y0, x1, y1 = info["bbox"]
        if x1 - x0 < 16 or y1 - y0 < 16 or not info.get("xref"):
            continue
        if has_text and (x1 - x0) * (y1 - y0) > 0.85 * w * h:
            continue  # a page background behind real text
        png = _image_png(doc, info["xref"])
        if png is None:
            continue
        name = f"p{index + 1:04d}_img{n + 1}.png"
        (workdir / name).write_bytes(png)
        regions.append({"type": "image", "bbox": [x0, y0, x1, y1], "file": name})

    if not has_text and not any(r["type"] == "image" for r in regions):
        if page.get_drawings() or page.get_images():
            name = f"p{index + 1:04d}_page.png"
            page.get_pixmap(dpi=150).save(str(workdir / name))
            regions.append({"type": "image", "bbox": [0, 0, w, h], "file": name})
    if not has_text and regions:
        warnings.append(f"第 {index + 1} 頁沒有文字層，已以圖片放入，文字未擷取。")

    for t in tables:
        regions.append({"type": "table", "bbox": t["bbox"], "rows": t["rows"]})

    order = reading_order([tuple(r["bbox"]) for r in regions], vertical=page_dir == "v")
    regions = [regions[i] for i in order]

    return {
        "index": index,
        "width": w,
        "height": h,
        "dir": page_dir,
        "regions": regions,
        "warnings": warnings,
        "ruby": ruby_count,
    }


def page_path(workdir: Path, index: int) -> Path:
    return workdir / f"page_{index + 1:04d}.json"


def convert(pdf_path, out_path, options: Options, workdir: Path, password: str | None = None,
            progress=None, should_stop=None) -> dict:
    """Convert a whole PDF. Pages already analysed in ``workdir`` are reused.

    ``progress(done, total)`` is called after each page; ``should_stop()``
    returning True stops between pages (the work done so far is kept).
    Returns write_docx's summary, or raises InterruptedError when stopped.
    """
    from .docx_writer import write_docx

    workdir.mkdir(parents=True, exist_ok=True)
    doc = open_pdf(pdf_path, password)
    total = doc.page_count
    pages = []
    for i in range(total):
        cached = page_path(workdir, i)
        if cached.exists():
            pages.append(json.loads(cached.read_text("utf-8")))
        else:
            if should_stop and should_stop():
                raise InterruptedError
            data = analyze_page(doc, i, options, workdir)
            cached.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            pages.append(data)
        if progress:
            progress(i + 1, total)
    doc.close()
    return write_docx(pages, options, workdir, out_path)
