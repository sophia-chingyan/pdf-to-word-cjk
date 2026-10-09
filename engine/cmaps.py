"""Read text in fonts encoded with a Unicode CMap as the Unicode it is.

With an encoding such as UniGB-UCS2-H, UniJIS-UTF16-V or UniKS-UTF8-H the
bytes in the PDF are Unicode code points (UCS-2, UTF-16, UTF-8 or UTF-32).
MuPDF turns them into CIDs of the encoding's character collection (GB1,
CNS1, Japan1, Korea1) and back into text through a collection table, which
goes wrong in several ways:

- Producers pair the encoding with a font of another collection (ReportLab
  writes MSung-Light, a CNS1 font, with UniGB-UCS2-H), so every character
  comes out as an unrelated Han character.
- Characters outside the encoding's collection are dropped: Hangul under
  UniGB/UniCNS/UniJIS, Simplified Chinese under UniCNS/UniJIS/UniKS.
- MuPDF has no UTF-8 or UTF-32 CMaps, nor UniJIS2004/UniAKR, so those read
  as single-byte garbage.

So each such font gets an embedded encoding that maps every code to the CID
equal to its code point, an identity ToUnicode map, and widths rewritten
for the new CIDs, keeping character positions as they were. Only the open
document is changed, not the file.
"""

from __future__ import annotations

import re

import pymupdf

PREFIX = "CodePoint-"  # names the CMaps written here
UNICODE_CMAP = re.compile(r"(Uni[A-Za-z0-9]+)-(UCS2|UTF8|UTF16|UTF32)(?:-HW)?-([HV])")
NUMBER = re.compile(r"\[|\]|-?\d+(?:\.\d+)?|-?\.\d+")


def _ranges(form: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, int]]]:
    """Codespace ranges and (low code, high code, first code point) runs."""
    if form == "UCS2":
        return [("0000", "FFFF")], [("0000", "FFFF", 0)]
    if form == "UTF32":
        return [("00000000", "0010FFFF")], [("00000000", "0010FFFF", 0)]
    if form == "UTF16":
        runs = [("0000", "D7FF", 0), ("E000", "FFFF", 0xE000)]
        runs += [(f"{hi:04X}DC00", f"{hi:04X}DFFF", 0x10000 + (hi - 0xD800) * 1024)
                 for hi in range(0xD800, 0xDC00)]
        return [("0000", "D7FF"), ("D800DC00", "DBFFDFFF"), ("E000", "FFFF")], runs
    # UTF-8: only the last byte runs in order, over 64 values.
    runs = [("00", "7F", 0)]
    for cp in range(0x80, 0x110000, 64):
        if 0xD800 <= cp < 0xE000:
            continue
        lo = chr(cp).encode()
        runs.append((lo.hex().upper(), (lo[:-1] + bytes([lo[-1] + 63])).hex().upper(), cp))
    return [("00", "7F"), ("C080", "DFBF"), ("E08080", "EFBFBF"), ("F0808080", "F4BFBFBF")], runs


def _cmap(name: str, kind: int, wmode: int, codespace, section: str, lines: list[str]) -> bytes:
    out = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
           "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def",
           f"/CMapName /{name} def", f"/CMapType {kind} def", f"/WMode {wmode} def",
           f"{len(codespace)} begincodespacerange"]
    out += [f"<{lo}> <{hi}>" for lo, hi in codespace]
    out.append("endcodespacerange")
    for i in range(0, len(lines), 100):
        chunk = lines[i:i + 100]
        out += [f"{len(chunk)} begin{section}", *chunk, f"end{section}"]
    out += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end", ""]
    return "\n".join(out).encode()


def _utf16_hex(cp: int) -> str:
    return chr(cp).encode("utf-16-be").hex().upper()


def _array(doc, xref: int, key: str) -> list:
    """A number array from a font dictionary, nested one level, or []."""
    kind, value = doc.xref_get_key(xref, key)
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    elif kind != "array":
        return []
    out: list = []
    stack = [out]
    for tok in NUMBER.findall(value):
        if tok == "[":
            stack.append([])
            stack[-2].append(stack[-1])
        elif tok == "]":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(float(tok))
    return out[0] if len(out) == 1 and isinstance(out[0], list) else out


def _metrics(items: list, per: int) -> dict[int, tuple]:
    """CID -> metrics from a W (per=1) or W2 (per=3) array."""
    out: dict[int, tuple] = {}
    i = 0
    while i < len(items):
        first = int(items[i])
        if i + 1 < len(items) and isinstance(items[i + 1], list):
            vals = items[i + 1]
            for k in range(len(vals) // per):
                out[first + k] = tuple(vals[k * per:(k + 1) * per])
            i += 2
        elif i + 2 + per <= len(items):
            last = int(items[i + 1])
            vals = tuple(items[i + 2:i + 2 + per])
            for cid in range(first, last + 1):
                out[cid] = vals
            i += 2 + per
        else:
            break
    return out


def _format(metrics: dict[int, tuple]) -> str:
    parts = []
    run: list[int] = []
    for cp in sorted(metrics) + [None]:
        if run and (cp is None or cp != run[-1] + 1):
            vals = " ".join(" ".join(f"{v:g}" for v in metrics[c]) for c in run)
            parts.append(f"{run[0]} [{vals}]")
            run = []
        if cp is not None:
            run.append(cp)
    return "[" + " ".join(parts) + "]"


def _code_to_cid(encoding: str, prefix: str, wmode: str):
    """How the original encoding turned a BMP code point into a CID."""
    bases = [prefix, "UniJIS"] if prefix.startswith("UniJIS") else [prefix]
    for name in [encoding] + [f"{b}-{form}-{wmode}" for b in bases for form in ("UCS2", "UTF16")]:
        try:
            cmap = pymupdf.mupdf.pdf_load_system_cmap(name)
        except Exception:
            continue
        return lambda cp: pymupdf.mupdf.pdf_lookup_cmap(cmap, cp)
    # Every Adobe CJK collection starts with ASCII at CID 1.
    return lambda cp: cp - 31 if 0x20 <= cp <= 0x7E else -1


def _descendant(doc, xref: int) -> int | None:
    kind, value = doc.xref_get_key(xref, "DescendantFonts")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    m = re.fullmatch(r"\s*\[\s*(\d+)\s+\d+\s+R\s*\]\s*", value or "")
    if m:
        return int(m.group(1))
    inner = (value or "").strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        return None
    # The CIDFont sits inline in the array; give it its own object.
    new = doc.get_new_xref()
    doc.update_object(new, inner[1:-1].strip())
    doc.xref_set_key(xref, "DescendantFonts", f"[{new} 0 R]")
    return new


def _fix_font(doc, xref: int, encoding: str, streams: dict) -> None:
    prefix, form, wmode = UNICODE_CMAP.fullmatch(encoding).groups()
    desc = _descendant(doc, xref)
    if desc is not None:
        to_cid = _code_to_cid(encoding, prefix, wmode)
        for key, per in (("W", 1), ("W2", 3)):
            old = _metrics(_array(doc, desc, key), per)
            if not old:
                continue
            new = {}
            for cp in range(0x10000):
                cid = to_cid(cp)
                if cid in old:
                    new[cp] = old[cid]
            doc.xref_set_key(desc, key, _format(new))

    key = (form, wmode)
    if key not in streams:
        codespace, runs = _ranges(form)
        enc = doc.get_new_xref()
        doc.update_object(enc, f"<< /Type /CMap /CMapName /{PREFIX}{form}-{wmode} /WMode {int(wmode == 'V')} "
                               "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>")
        doc.update_stream(enc, _cmap(f"{PREFIX}{form}-{wmode}", 1, int(wmode == "V"), codespace, "cidrange",
                                     [f"<{lo}> <{hi}> {cp}" for lo, hi, cp in runs]))
        uni = doc.get_new_xref()
        doc.update_object(uni, "<<>>")
        doc.update_stream(uni, _cmap(f"{PREFIX}{form}-UCS", 2, 0, codespace, "bfrange",
                                     [f"<{lo}> <{hi}> <{_utf16_hex(cp)}>" for lo, hi, cp in runs]))
        streams[key] = (enc, uni)
    enc, uni = streams[key]
    doc.xref_set_key(xref, "Encoding", f"{enc} 0 R")
    doc.xref_set_key(xref, "ToUnicode", f"{uni} 0 R")


def needs_cid_text(page) -> bool:
    """Whether text on this page must be read with CIDs as code points.

    MuPDF only applies a ToUnicode map to 2-byte codes, so for fonts
    rewritten here from UTF-8, UTF-16 (outside the BMP) or UTF-32 the text
    comes from the CID, which equals the code point.
    """
    doc = page.parent
    for xref, _ext, kind, *_ in page.get_fonts(full=True):
        if kind != "Type0":
            continue
        enc_kind, value = doc.xref_get_key(xref, "Encoding")
        if enc_kind == "xref":
            name = doc.xref_get_key(int(value.split()[0]), "CMapName")[1]
            if name.startswith(f"/{PREFIX}UTF"):
                return True
    return False


def fix_unicode_cmaps(doc) -> int:
    """Rewrite every Type0 font with a Unicode CMap encoding; returns how many."""
    fixed: set[int] = set()
    streams: dict = {}
    for page in doc:
        for xref, _ext, kind, _name, _ref, encoding, *_ in page.get_fonts(full=True):
            if xref in fixed or kind != "Type0" or not UNICODE_CMAP.fullmatch(encoding or ""):
                continue
            _fix_font(doc, xref, encoding, streams)
            fixed.add(xref)
    return len(fixed)
