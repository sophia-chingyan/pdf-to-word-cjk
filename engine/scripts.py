"""Character classification, language detection and Traditional/Simplified hints."""

from __future__ import annotations

# Characters that differ between Traditional and Simplified Chinese. Each
# string holds frequent characters of one form only; counting hits on both
# sides is enough to tell the two apart in ordinary text.
TRAD_ONLY = set(
    "這個們來時為說國會對學發經過還產與後點動關問進種實現從當應裡開長樣"
    "麼覺電話書車體頭邊聽讀寫見聲業議題機據處義區記數務總馬鳥魚門間陽陰"
    "條讓請認識變買賣愛歡華東務員場氣錢銀龍飛風雲語調設計論應該將並萬與"
    "幾歲們傳報導濟歷殺戰權線聯網達選連運還遠農醫響順類顯驗險"
)
SIMP_ONLY = set(
    "这个们来时为说国会对学发经过还产与后点动关问进种实现从当应里开长样"
    "么觉电话书车体头边听读写见声业议题机据处义区记数务总马鸟鱼门间阳阴"
    "条让请认识变买卖爱欢华东务员场气钱银龙飞风云语调设计论应该将并万与"
    "几岁们传报导济历杀战权线联网达选连运还远农医响顺类显验险"
)


def is_hiragana(c: str) -> bool:
    return "぀" <= c <= "ゟ"


def is_katakana(c: str) -> bool:
    return "゠" <= c <= "ヿ" or "ㇰ" <= c <= "ㇿ" or "ｦ" <= c <= "ﾟ"


def is_kana(c: str) -> bool:
    return is_hiragana(c) or is_katakana(c)


def is_han(c: str) -> bool:
    o = ord(c)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0x20000 <= o <= 0x2FA1F
        or 0xF900 <= o <= 0xFAFF
        or c in "々〆〇ヶ"
    )


def is_hangul(c: str) -> bool:
    o = ord(c)
    return 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F


def is_cjk_punct(c: str) -> bool:
    o = ord(c)
    return 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF or 0xFE10 <= o <= 0xFE4F


def is_cjk(c: str) -> bool:
    """True for characters that are written without spaces between them."""
    return is_han(c) or is_kana(c) or is_cjk_punct(c)


def is_broken(c: str) -> bool:
    o = ord(c)
    return c == "�" or 0xE000 <= o <= 0xF8FF


LANG_CODES = ("zh-TW", "zh-CN", "ja-JP", "ko-KR")


def script_counts(text: str) -> dict:
    counts = {"han": 0, "kana": 0, "hangul": 0, "latin": 0, "trad": 0, "simp": 0}
    for c in text:
        if is_kana(c):
            counts["kana"] += 1
        elif is_han(c):
            counts["han"] += 1
            if c in TRAD_ONLY:
                counts["trad"] += 1
            elif c in SIMP_ONLY:
                counts["simp"] += 1
        elif is_hangul(c):
            counts["hangul"] += 1
        elif c.isalpha():
            counts["latin"] += 1
    return counts


def detect_language(text: str, allowed: list[str] | None = None, doc_hint: str | None = None) -> str:
    """Pick one of LANG_CODES for a block of text.

    ``allowed`` restricts the answer to the languages the owner ticked.
    ``doc_hint`` is the document-wide guess, used when the block alone is
    ambiguous (for example a Kanji-only heading in a Japanese book).
    """
    allowed = [a for a in (allowed or []) if a in LANG_CODES] or list(LANG_CODES)
    if len(allowed) == 1:
        return allowed[0]
    c = script_counts(text)
    if c["kana"] and "ja-JP" in allowed:
        return "ja-JP"
    if c["hangul"] and "ko-KR" in allowed:
        return "ko-KR"
    if c["han"]:
        if doc_hint in allowed and doc_hint in ("ja-JP", "ko-KR") and c["trad"] == c["simp"]:
            return doc_hint
        if c["trad"] > c["simp"] and "zh-TW" in allowed:
            return "zh-TW"
        if c["simp"] > c["trad"] and "zh-CN" in allowed:
            return "zh-CN"
    if doc_hint in allowed:
        return doc_hint
    # Owner is in Taiwan: Traditional Chinese is the fallback when allowed.
    for pref in ("zh-TW", "ja-JP", "zh-CN", "ko-KR"):
        if pref in allowed:
            return pref
    return allowed[0]


def needs_space(left: str, right: str) -> bool:
    """Whether joining two wrapped lines needs a space between them."""
    if not left or not right:
        return False
    a, b = left[-1], right[0]
    if a.isspace() or b.isspace():
        return False
    if is_cjk(a) or is_cjk(b):
        return False
    return True
