"""Замена найденных персональных данных по выбранному режиму."""
import re
from collections import Counter
from typing import Optional

from .detectors import LABELS, find_pii

MODES = ("tag", "pseudo", "stars")


class Masker:
    """Один экземпляр на документ: хранит статистику и соответствия для режима pseudo."""

    def __init__(self, mode: str = "tag", kinds: Optional[set[str]] = None):
        if mode not in MODES:
            raise ValueError(f"Неизвестный режим: {mode}")
        self.mode = mode
        self.kinds = kinds
        self.stats: Counter = Counter()
        self._pseudo: dict[tuple[str, str], int] = {}
        self._counters: Counter = Counter()

    def _replacement(self, kind: str, value: str) -> str:
        if self.mode == "stars":
            return re.sub(r"[\w]", "*", value)
        if self.mode == "pseudo":
            key = (kind, re.sub(r"[\W_]+", "", value).lower())
            if key not in self._pseudo:
                self._counters[kind] += 1
                self._pseudo[key] = self._counters[kind]
            return f"[{LABELS[kind]}_{self._pseudo[key]}]"
        return f"[{LABELS[kind]}]"

    def replacements(self, text: str) -> list[tuple[int, int, str]]:
        """[(start, end, замена)] для найденных ПДн; обновляет статистику."""
        result = []
        for m in find_pii(text, self.kinds):
            result.append((m.start, m.end, self._replacement(m.kind, text[m.start:m.end])))
            self.stats[m.kind] += 1
        return result

    def mask_text(self, text: str) -> str:
        out, pos = [], 0
        for start, end, repl in self.replacements(text):
            out.append(text[pos:start])
            out.append(repl)
            pos = end
        out.append(text[pos:])
        return "".join(out)
