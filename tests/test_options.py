from engine.options import Options
from engine.scripts import detect_language


def test_defaults_are_auto():
    o = Options.from_dict({})
    assert o.auto and o.languages == [] and o.forced_direction is None


def test_single_direction_is_forced():
    o = Options.from_dict({"choices": ["zh_tra_v", "ja_v"]})
    assert o.forced_direction == "v"
    assert o.languages == ["zh-TW", "ja-JP"]


def test_both_directions_detect_per_block():
    assert Options.from_dict({"choices": ["zh_tra_v", "zh_tra_h"]}).forced_direction is None


def test_unknown_values_are_ignored():
    o = Options.from_dict({"choices": ["xx"], "furigana": "nope"})
    assert o.auto and o.furigana == "brackets"


def test_language_detection():
    assert detect_language("這是繁體中文的句子") == "zh-TW"
    assert detect_language("这是简体中文的句子") == "zh-CN"
    assert detect_language("これは日本語です") == "ja-JP"
    assert detect_language("한국어 문장입니다") == "ko-KR"
    assert detect_language("漢字", allowed=["ja-JP", "zh-TW"], doc_hint="ja-JP") == "ja-JP"
