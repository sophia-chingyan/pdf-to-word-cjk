import pymupdf
import pytest
from docx import Document
from docx.oxml.ns import qn

from engine.convert import convert, open_pdf
from engine.options import Options

W_TD = qn("w:textDirection")


def run(samples, tmp_path, name, **opts):
    out = tmp_path / f"{name}.docx"
    summary = convert(samples[name], out, Options.from_dict(opts or None), tmp_path / "work")
    return Document(out), summary


def body_text(doc):
    return [p.text for p in doc.paragraphs if p.text.strip()]


def section_dirs(doc):
    return [(s._sectPr.find(W_TD).get(qn("w:val")) if s._sectPr.find(W_TD) is not None else None)
            for s in doc.sections]


def test_vertical_japanese_with_furigana(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "ja_vertical_ruby")
    assert summary["directions"] == ["v"]
    assert summary["languages"] == ["ja-JP"]
    assert section_dirs(doc) == ["tbRl"]
    text = "\n".join(body_text(doc))
    assert "見当(けんとう)がつかぬ" in text
    assert "人間(にんげん)というもの" in text
    assert doc.paragraphs[0].style.name == "Heading 1" or body_text(doc)[0] == "吾輩は猫である"


def test_furigana_can_be_dropped(samples, tmp_path):
    doc, _ = run(samples, tmp_path, "ja_vertical_ruby", choices=["ja_v"], furigana="drop")
    text = "\n".join(body_text(doc))
    assert "見当がつかぬ" in text
    assert "けんとう" not in text


def test_vertical_paragraphs_run_on_across_pages(samples, tmp_path):
    doc, _ = run(samples, tmp_path, "ja_vertical_long")
    expected = [f"　第{i}段落。" + "親譲りの無鉄砲で小供の時から損ばかりしている。" * 14 for i in range(1, 9)]
    assert body_text(doc) == expected


def test_traditional_chinese_structure(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "zh_tw_horizontal")
    assert summary["languages"][0] == "zh-TW"
    styles = {p.text: p.style.name for p in doc.paragraphs if p.text}
    assert styles["臺灣的歷史與文化"] == "Heading 1"
    assert styles["第一節　概述"] == "Heading 2"
    assert styles["第一個重點項目"] == "List Bullet"
    assert [c.text for c in doc.tables[0].rows[1].cells] == ["臺北", "250萬", "272"]
    assert len(doc.inline_shapes) == 1
    assert section_dirs(doc) == [None]


def test_two_column_reading_order(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "zh_cn_two_columns")
    assert summary["languages"] == ["zh-CN"]
    paras = body_text(doc)
    assert len(paras) == 6
    for i, p in enumerate(paras, 1):
        assert p.startswith(f"第{i}段：") and p.endswith("是否正确。")


def test_vertical_block_on_horizontal_page(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "mixed_directions")
    assert section_dirs(doc) == [None]
    cell = doc.tables[0].cell(0, 0)
    assert cell.text == "直排標語文字保持不變"
    assert cell._tc.tcPr.find(W_TD).get(qn("w:val")) == "tbRl"


def test_korean(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "ko_horizontal")
    assert summary["languages"] == ["ko-KR"]
    assert "이 문서는 한국어 텍스트가" in "\n".join(body_text(doc))


def test_forced_vertical_output(samples, tmp_path):
    doc, summary = run(samples, tmp_path, "zh_tw_horizontal", choices=["zh_tra_v"])
    assert section_dirs(doc) == ["tbRl"]
    assert summary["languages"] == ["zh-TW"]


def test_pause_resume_reuses_finished_pages(samples, tmp_path):
    work = tmp_path / "work"
    calls = []

    def stop_after_first():
        return len(calls) >= 1

    import pytest
    with pytest.raises(InterruptedError):
        convert(samples["ja_vertical_long"], tmp_path / "a.docx", Options(), work,
                progress=lambda d, t: calls.append(d), should_stop=stop_after_first)
    assert (work / "page_0001.json").exists() and not (work / "page_0002.json").exists()
    convert(samples["ja_vertical_long"], tmp_path / "a.docx", Options(), work)
    assert (tmp_path / "a.docx").exists()



def unicode_cmap_pdf(path, encoding, ordering, lines, codec, vertical=False):
    """A page in a non-embedded CID font with a Unicode CMap encoding, the way
    ReportLab and other generators write it (often with a mismatched font)."""
    pdf = pymupdf.open()
    page = pdf.new_page()
    font = pdf.get_new_xref()
    pdf.update_object(font, (
        f"<< /Type /Font /Subtype /Type0 /BaseFont /F /Encoding /{encoding} "
        "/DescendantFonts [ << /Type /Font /Subtype /CIDFontType0 /BaseFont /F "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering ({ordering}) /Supplement 1 >> /DW 1000 "
        "/W [ 1 [ 250 ] 34 [ 615 ] 67 [ 521 427 ] ] "
        "/FontDescriptor << /Type /FontDescriptor /FontName /F /Flags 6 "
        "/FontBBox [ -160 -249 1015 888 ] /ItalicAngle 0 /Ascent 752 /Descent -271 "
        "/CapHeight 737 /StemV 58 >> >> ] >>"))
    pdf.xref_set_key(page.xref, "Resources", f"<< /Font << /F2 {font} 0 R >> >>")
    ops = []
    for i, line in enumerate(lines):
        x, y = (500 - 18 * i, 760) if vertical else (72, 760 - 18 * i)
        ops.append(f"BT /F2 12 Tf {x} {y} Td <{line.encode(codec).hex()}> Tj ET")
    contents = pdf.get_new_xref()
    pdf.update_object(contents, "<<>>")
    pdf.update_stream(contents, "\n".join(ops).encode())
    pdf.xref_set_key(page.xref, "Contents", f"{contents} 0 R")
    pdf.save(path)
    return path


UNICODE_CMAP_CASES = [
    # ReportLab: MSung-Light (CNS1) with UniGB-UCS2-H.
    ("UniGB-UCS2-H", "CNS1", "utf-16-be", ["小我：人類的現狀，喬治·歐威爾⋯⋯"], "zh-TW"),
    ("UniGB-UCS2-H", "GB1", "utf-16-be", ["这是简体中文的测试段落，检查转换是否正确。"], "zh-CN"),
    ("UniCNS-UCS2-H", "CNS1", "utf-16-be", ["这是简体中文的测试段落，检查转换是否正确。"], "zh-CN"),
    ("UniJIS-UCS2-H", "Japan1", "utf-16-be", ["これは日本語のテストです。カタカナと漢字。"], "ja-JP"),
    ("UniGB-UCS2-H", "Japan1", "utf-16-be", ["これは日本語のテストです。カタカナと漢字。"], "ja-JP"),
    ("UniKS-UCS2-H", "Korea1", "utf-16-be", ["이 문서는 한국어 테스트입니다."], "ko-KR"),
    ("UniGB-UCS2-H", "Korea1", "utf-16-be", ["이 문서는 한국어 테스트입니다."], "ko-KR"),
    ("UniJIS-UTF16-H", "Japan1", "utf-16-be", ["𠮷野家の漢字テスト。"], "ja-JP"),
    ("UniJIS-UTF8-H", "Japan1", "utf-8", ["これは日本語のテストです。"], "ja-JP"),
    ("UniKS-UTF8-H", "Korea1", "utf-8", ["이 문서는 한국어 테스트입니다."], "ko-KR"),
    ("UniCNS-UTF32-H", "CNS1", "utf-32-be", ["繁體中文測試，這是一個段落。"], "zh-TW"),
    ("UniAKR-UTF16-H", "Korea1", "utf-16-be", ["이 문서는 한국어 테스트입니다."], "ko-KR"),
]


@pytest.mark.parametrize("encoding,ordering,codec,lines,lang", UNICODE_CMAP_CASES)
def test_unicode_cmap_fonts(tmp_path, encoding, ordering, codec, lines, lang):
    src = unicode_cmap_pdf(tmp_path / "in.pdf", encoding, ordering, lines, codec)
    out = tmp_path / "out.docx"
    summary = convert(src, out, Options.from_dict(None), tmp_path / "work")
    text = "\n".join(body_text(Document(out)))
    for line in lines:
        assert line in text
    assert summary["languages"] == [lang]


def test_unicode_cmap_keeps_latin_widths(tmp_path):
    src = unicode_cmap_pdf(tmp_path / "in.pdf", "UniKS-UTF8-H", "CNS1", ["Abc 한"], "utf-8")
    page = open_pdf(src)[0]
    chars = [ch for b in page.get_text("rawdict", flags=pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE)["blocks"]
             for ln in b["lines"] for sp in ln["spans"] for ch in sp["chars"]]
    assert "".join(c["c"] for c in chars).replace("\xa0", " ") == "Abc 한"
    # Widths 615, 521, 427, 250 from the font's W array, 12 pt.
    assert [round(c["bbox"][2] - c["bbox"][0], 2) for c in chars] == [7.38, 6.25, 5.12, 3.0, 12.0]


def test_unicode_cmap_vertical(tmp_path):
    lines = ["吾輩は猫である。名前はまだ無い。", "どこで生れたかとんと見当がつかぬ。"]
    src = unicode_cmap_pdf(tmp_path / "in.pdf", "UniJIS-UCS2-V", "GB1", lines, "utf-16-be", vertical=True)
    out = tmp_path / "out.docx"
    summary = convert(src, out, Options.from_dict(None), tmp_path / "work")
    text = "".join(body_text(Document(out)))
    assert "".join(lines) in text
    assert summary["directions"] == ["v"]
