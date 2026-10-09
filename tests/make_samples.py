"""Build sample CJK PDFs for tests: Word documents rendered to PDF by LibreOffice.

LibreOffice lays out vertical text and ruby the way real publishing tools do,
so the PDFs exercise the same extraction paths as real books.

    python tests/make_samples.py OUTDIR
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pymupdf
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


def _font(doc, east_asia: str, size: float = 11):
    doc.styles["Normal"].font.size = Pt(size)
    for name in ("Normal", "Heading 1", "Heading 2", "Title"):
        rpr = doc.styles[name].element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.insert(0, fonts)
        for attr in ("w:eastAsia", "w:ascii", "w:hAnsi"):
            fonts.set(qn(attr), east_asia)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme"):
            fonts.attrib.pop(qn(attr), None)


def _vertical(section):
    td = OxmlElement("w:textDirection")
    td.set(qn("w:val"), "tbRl")
    grid = section._sectPr.find(qn("w:docGrid"))
    if grid is not None:
        grid.addprevious(td)
    else:
        section._sectPr.append(td)


def _ruby(paragraph, base: str, reading: str):
    r = OxmlElement("w:r")
    ruby = OxmlElement("w:ruby")
    pr = OxmlElement("w:rubyPr")
    for tag, val in (("w:rubyAlign", "distributeSpace"), ("w:hps", "10"), ("w:hpsRaise", "20"),
                     ("w:hpsBaseText", "22"), ("w:lid", "ja-JP")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        pr.append(e)
    ruby.append(pr)
    for tag, text, size in (("w:rt", reading, "10"), ("w:rubyBase", base, "22")):
        holder = OxmlElement(tag)
        rr = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), size)
        rpr.append(sz)
        rr.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        rr.append(t)
        holder.append(rr)
        ruby.append(holder)
    r.append(ruby)
    paragraph._p.append(r)


def _png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pix.set_rect(pix.irect, (40, 120, 200))
    return pix.tobytes("png")


def zh_tw_horizontal(path: Path):
    doc = Document()
    _font(doc, "WenQuanYi Zen Hei")
    doc.add_heading("臺灣的歷史與文化", level=1)
    doc.add_paragraph("這是一份測試文件，用來確認轉換器能夠正確處理繁體中文的段落、標題、圖片與表格。" * 3)
    doc.add_heading("第一節　概述", level=2)
    doc.add_paragraph("臺灣位於東亞，島上有豐富的自然資源與多元的文化。這裡的人們說國語、臺語與客家話。" * 2)
    doc.add_picture(io.BytesIO(_png()), width=Cm(4))
    t = doc.add_table(rows=3, cols=3)
    t.style = "Table Grid"
    for i, row in enumerate([("城市", "人口", "面積"), ("臺北", "250萬", "272"), ("高雄", "273萬", "2952")]):
        for j, v in enumerate(row):
            t.cell(i, j).text = v
    doc.add_paragraph("• 第一個重點項目")
    doc.add_paragraph("• 第二個重點項目")
    doc.save(path)


def ja_vertical_ruby(path: Path):
    doc = Document()
    _font(doc, "IPAGothic", 11)
    _vertical(doc.sections[0])
    doc.add_heading("吾輩は猫である", level=1)
    p = doc.add_paragraph("　吾輩は猫である。名前はまだ無い。どこで生れたかとんと")
    _ruby(p, "見当", "けんとう")
    p.add_run("がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。")
    p = doc.add_paragraph("　吾輩はここで始めて")
    _ruby(p, "人間", "にんげん")
    p.add_run("というものを見た。しかもあとで聞くとそれは書生という人間中で一番獰悪な種族であったそうだ。" * 2)
    doc.save(path)


def zh_cn_two_columns(path: Path):
    doc = Document()
    _font(doc, "WenQuanYi Zen Hei")
    sect = doc.sections[0]
    cols = sect._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect._sectPr.append(cols)
    cols.set(qn("w:num"), "2")
    cols.set(qn("w:space"), "720")
    for i in range(1, 7):
        doc.add_paragraph(f"第{i}段：这是简体中文的测试段落，用来检查双栏版面的阅读顺序是否正确。" * 3)
    doc.save(path)


def ko_horizontal(path: Path):
    doc = Document()
    _font(doc, "WenQuanYi Zen Hei")
    doc.add_heading("한국어 테스트 문서", level=1)
    doc.add_paragraph("이 문서는 한국어 텍스트가 올바르게 변환되는지 확인하기 위한 테스트입니다. " * 4)
    doc.save(path)


def mixed_directions(path: Path):
    """A horizontal page with a vertical slogan column, written directly with
    PyMuPDF one character at a time, the way many layout tools emit it."""
    font = _cjk_font_file()
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="cjk", fontfile=font)
    page.insert_textbox(pymupdf.Rect(72, 72, 440, 300),
                        "這一頁的正文是橫排的繁體中文。右邊的標語是直排的，轉換後應該保持直排。" * 3,
                        fontname="cjk", fontsize=12)
    y = 80
    for ch in "直排標語文字保持不變":
        page.insert_text((500, y + 16), ch, fontname="cjk", fontsize=16)
        y += 18
    pdf.save(path.with_suffix(".pdf"))


def _cjk_font_file() -> str:
    for cand in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(cand).exists():
            return cand
    raise SystemExit("No CJK font found to build samples")


def ja_vertical_long(path: Path):
    """Three vertical pages; paragraphs run on across page breaks."""
    doc = Document()
    _font(doc, "IPAGothic", 11)
    _vertical(doc.sections[0])
    for i in range(1, 9):
        doc.add_paragraph(f"　第{i}段落。" + "親譲りの無鉄砲で小供の時から損ばかりしている。" * 14)
    doc.save(path)


SAMPLES = {
    "mixed_directions": mixed_directions,
    "ja_vertical_long": ja_vertical_long,
    "zh_tw_horizontal": zh_tw_horizontal,
    "ja_vertical_ruby": ja_vertical_ruby,
    "zh_cn_two_columns": zh_cn_two_columns,
    "ko_horizontal": ko_horizontal,
}


def build(outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, fn in SAMPLES.items():
        pdf = outdir / f"{name}.pdf"
        if not pdf.exists():
            src = outdir / f"{name}.docx"
            fn(src)
            if pdf.exists():  # the builder wrote the PDF itself
                out[name] = pdf
                continue
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
                check=True, capture_output=True, timeout=180,
            )
        out[name] = pdf
    return out


if __name__ == "__main__":
    for name, p in build(Path(sys.argv[1] if len(sys.argv) > 1 else "samples")).items():
        print(name, p)
