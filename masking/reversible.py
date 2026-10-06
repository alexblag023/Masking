"""Обратимое маскирование и демаскирование одного абзаца/ячейки.

Отвечает за замену в произвольной строке. Проходы по узлам docx/xlsx — в
docx_proc.py / xlsx_proc.py; здесь — всё, что касается сущностей и токенов.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import registry
from .entities import Span, find_entities
from .morph import analyze, inflect
from .ner import spans as ner_spans
from .tokens import TOKEN_RE, make_token, parse_token


@dataclass
class MaskStats:
    found: Counter = field(default_factory=Counter)   # всего найдено по типу
    new: Counter = field(default_factory=Counter)     # впервые встреченные
    reused: Counter = field(default_factory=Counter)  # уже известные в проекте

    def as_dict(self) -> dict:
        return {
            "found":  dict(self.found),
            "new":    dict(self.new),
            "reused": dict(self.reused),
            "total":  sum(self.found.values()),
        }


class ReversibleMasker:
    """Один экземпляр на обработку документа. Привязан к проекту.

    `kinds` — какие типы маскировать. По умолчанию ФИО и адреса. Остальные
    типы (телефоны/ИНН/...) обрабатываются необратимым путём, см. masker.py.
    """

    def __init__(
        self,
        project_id: int,
        kinds: frozenset[str] = frozenset({"FIO", "ADDR"}),
        detect_fn: Callable[[str], list] | None = None,
    ):
        self.project_id = project_id
        self.kinds = kinds
        self.stats = MaskStats()
        self._known_seqs: set[int] = {
            e["id"] for e in registry.list_entities(project_id)
        }
        self._detect = detect_fn or (lambda t: find_entities(t, ner_spans(t)))
        self._pending: list[tuple[int, str, str]] = []
        self._current_location: str = "unknown"

    def set_location(self, location: str) -> None:
        """Устанавливает место для последующих вызовов mask_text()."""
        self._current_location = location

    def mask_text(self, text: str) -> str:
        """Маскирует текст, запоминая вхождения с текущей location."""
        location = self._current_location
        if not text or text.isspace():
            return text
        found = [s for s in self._detect(text) if s.kind in self.kinds]
        if not found:
            return text
        out: list[str] = []
        pos = 0
        for span in found:
            out.append(text[pos:span.start])
            surface = text[span.start:span.end]
            entity, case_code = self._resolve(span, surface)
            out.append(make_token(span.kind, entity["seq"], case_code))
            self._pending.append((entity["id"], location, case_code))
            self.stats.found[span.kind] += 1
            if entity["id"] in self._known_seqs:
                self.stats.reused[span.kind] += 1
            else:
                self.stats.new[span.kind] += 1
                self._known_seqs.add(entity["id"])
            pos = span.end
        out.append(text[pos:])
        return "".join(out)

    def flush(self, document_id: int) -> None:
        """Записывает накопленные вхождения в БД для указанного документа."""
        for eid, loc, case_code in self._pending:
            registry.add_occurrence(eid, document_id, loc, case_code)
        self._pending.clear()

    def _resolve(self, span: Span, surface: str) -> tuple[dict, str]:
        if span.kind == "FIO":
            canon, case_code, gender = analyze(surface)
            entity = registry.find_or_create_entity(
                self.project_id, "FIO", canon, gender,
            )
            registry.remember_form(entity["id"], case_code, surface)
            return entity, case_code
        # Адрес: без падежей, канон = первая встреченная форма.
        entity = registry.find_or_create_entity(self.project_id, "ADDR", surface, None)
        registry.remember_form(entity["id"], "nomn", surface)
        return entity, "nomn"


@dataclass
class UnmaskStats:
    restored: int = 0
    unknown: list[str] = field(default_factory=list)      # сами токены
    inflected: int = 0                                    # сколько форм склоняли

    def as_dict(self) -> dict:
        return {
            "restored":  self.restored,
            "unknown":   self.unknown,
            "inflected": self.inflected,
        }


class ReversibleUnmasker:
    """Демаскирование: токены -> оригинальные значения, с учётом падежа."""

    def __init__(self, project_id: int):
        self.project_id = project_id
        self.stats = UnmaskStats()
        # Кэш на проект: entity[kind,seq] -> dict
        self._cache: dict[tuple[str, int], Optional[dict]] = {}
        self._forms_cache: dict[int, dict[str, str]] = {}

    def _render(self, kind: str, seq: int, case_code: str) -> Optional[str]:
        key = (kind, seq)
        if key not in self._cache:
            self._cache[key] = registry.entity_by_seq(self.project_id, kind, seq)
        entity = self._cache[key]
        if entity is None:
            return None
        if kind == "ADDR":
            return entity["canonical"]
        # ФИО: сначала сохранённая форма в этом падеже, иначе склоняем.
        eid = entity["id"]
        if eid not in self._forms_cache:
            self._forms_cache[eid] = registry.entity_forms(eid)
        surface = self._forms_cache[eid].get(case_code)
        if surface:
            return surface
        if case_code == "nomn":
            return entity["canonical"]
        self.stats.inflected += 1
        return inflect(entity["canonical"], case_code, entity.get("gender"))

    def unmask_text(self, text: str) -> str:
        if not text or "[" not in text and "［" not in text:
            return text

        def _sub(m: re.Match) -> str:
            kind, seq, case_code = parse_token(m)
            value = self._render(kind, seq, case_code)
            if value is None:
                self.stats.unknown.append(m.group(0))
                return m.group(0)
            self.stats.restored += 1
            return value

        return TOKEN_RE.sub(_sub, text)
