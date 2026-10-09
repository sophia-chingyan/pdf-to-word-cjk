"""Content settings chosen by the owner before a conversion (spec D13)."""

from __future__ import annotations

from dataclasses import dataclass, field

# Value -> (language code, direction). Mirrors the OCR app's picker.
CHOICES = {
    "zh_tra_h": ("zh-TW", "h"),
    "zh_tra_v": ("zh-TW", "v"),
    "zh_sim_h": ("zh-CN", "h"),
    "zh_sim_v": ("zh-CN", "v"),
    "ja_h": ("ja-JP", "h"),
    "ja_v": ("ja-JP", "v"),
    "ko_h": ("ko-KR", "h"),
    "ko_v": ("ko-KR", "v"),
}
LABELS = {
    "auto": "自動偵測",
    "zh_tra_h": "繁體中文（橫排）",
    "zh_tra_v": "繁體中文（直排）",
    "zh_sim_h": "簡體中文（橫排）",
    "zh_sim_v": "簡體中文（直排）",
    "ja_h": "日文（橫排，含平假名、片假名、漢字）",
    "ja_v": "日文（直排，含平假名、片假名、漢字）",
    "ko_h": "韓文（橫排）",
    "ko_v": "韓文（直排）",
}


@dataclass
class Options:
    choices: list[str] = field(default_factory=lambda: ["auto"])
    furigana: str = "brackets"  # "brackets" | "drop"

    @classmethod
    def from_dict(cls, d: dict | None) -> "Options":
        d = d or {}
        choices = [c for c in d.get("choices", []) if c == "auto" or c in CHOICES] or ["auto"]
        furigana = d.get("furigana") if d.get("furigana") in ("brackets", "drop") else "brackets"
        return cls(choices=choices, furigana=furigana)

    def to_dict(self) -> dict:
        return {"choices": self.choices, "furigana": self.furigana}

    @property
    def auto(self) -> bool:
        return "auto" in self.choices or not any(c in CHOICES for c in self.choices)

    @property
    def languages(self) -> list[str]:
        """Languages allowed for fonts and tags; empty means any."""
        if self.auto:
            return []
        out = []
        for c in self.choices:
            if c in CHOICES and CHOICES[c][0] not in out:
                out.append(CHOICES[c][0])
        return out

    @property
    def forced_direction(self) -> str | None:
        """'h' or 'v' when only one direction is ticked; None means detect per block."""
        if self.auto:
            return None
        dirs = {CHOICES[c][1] for c in self.choices if c in CHOICES}
        return dirs.pop() if len(dirs) == 1 else None

    def label(self) -> str:
        return "、".join(LABELS.get(c, c) for c in self.choices)
