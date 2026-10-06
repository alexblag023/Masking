"""Поиск персональных данных в тексте: regex + проверка контрольных сумм."""
import re
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

# Метки типов и их приоритет при пересечении совпадений (меньше = важнее).
LABELS = {
    "card": "КАРТА",
    "snils": "СНИЛС",
    "email": "EMAIL",
    "phone": "ТЕЛЕФОН",
    "inn": "ИНН",
    "passport": "ПАСПОРТ",
    "birthdate": "ДАТА_РОЖДЕНИЯ",
    "fio": "ФИО",
}
PRIORITY = {kind: i for i, kind in enumerate(LABELS)}


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    kind: str


def _digits(s: str) -> list[int]:
    return [int(c) for c in s if c.isdigit()]


def luhn_ok(s: str) -> bool:
    d = _digits(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, v in enumerate(reversed(d)):
        if i % 2:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    return total % 10 == 0


def inn_ok(s: str) -> bool:
    d = _digits(s)
    if len(d) == 10:
        c = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return sum(a * b for a, b in zip(c, d)) % 11 % 10 == d[9]
    if len(d) == 12:
        c1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        n1 = sum(a * b for a, b in zip(c1, d)) % 11 % 10
        n2 = sum(a * b for a, b in zip(c2, d)) % 11 % 10
        return n1 == d[10] and n2 == d[11]
    return False


def snils_ok(s: str) -> bool:
    d = _digits(s)
    if len(d) != 11:
        return False
    total = sum(v * (9 - i) for i, v in enumerate(d[:9]))
    if total < 100:
        check = total
    elif total in (100, 101):
        check = 0
    else:
        check = total % 101
        if check in (100, 101):
            check = 0
    return check == d[9] * 10 + d[10]


@dataclass(frozen=True)
class Rule:
    kind: str
    pattern: re.Pattern
    group: int = 0
    group_end: Optional[int] = None  # если задан — спан от начала group до конца group_end
    validate: Optional[Callable[[str], bool]] = None


_CYR_UP = "А-ЯЁ"
_NAME = rf"[{_CYR_UP}][а-яё]+(?:-[{_CYR_UP}][а-яё]+)?"
_PATR = r"[А-ЯЁ][а-яё]+(?:вич|вна|ична|ьич|кызы|оглы|улы)"
_PATR_UP = r"[А-ЯЁ]+(?:ВИЧ|ВНА|ИЧНА|ЬИЧ|КЫЗЫ|ОГЛЫ|УЛЫ)"
_INI = rf"[{_CYR_UP}]\.\s?[{_CYR_UP}]\."

RULES = [
    Rule("card", re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), validate=luhn_ok),
    Rule("snils", re.compile(r"(?<!\d)\d{3}[\- ]\d{3}[\- ]\d{3}[ \-]\d{2}(?!\d)"), validate=snils_ok),
    Rule("snils", re.compile(r"(?i)снилс[^\d]{0,15}(\d{11})(?!\d)"), group=1, validate=snils_ok),
    Rule("email", re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")),
    Rule(
        "phone",
        re.compile(r"(?<![\w+])(?:\+7|[78])[\s\-]*\(?\d{3}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"),
    ),
    # ИНН физлица (12 цифр) — по контрольной сумме; 10 цифр (юрлицо) — только рядом со словом «ИНН».
    Rule("inn", re.compile(r"(?<!\d)\d{12}(?!\d)"), validate=inn_ok),
    Rule("inn", re.compile(r"(?i)инн[^\d]{0,15}(\d{10}|\d{12})(?!\d)"), group=1, validate=inn_ok),
    Rule("passport", re.compile(r"(?i)паспорт[^\d]{0,40}(\d{2}\s?\d{2}[\s,№N-]{0,3}\d{6})(?!\d)"), group=1),
    Rule("passport", re.compile(r"(?i)серия[^\d]{0,5}(\d{2}\s?\d{2})\s*(?:№|номер|N)?\s*(\d{6})(?!\d)"), group=1, group_end=2),
    Rule(
        "birthdate",
        re.compile(
            r"(?i)(?:дата\s+рождения|д\.\s?р\.|родил(?:ся|ась)|г\.\s?р\.)[:\s\-–]*(\d{1,2}[./]\d{1,2}[./]\d{2,4})"
        ),
        group=1,
    ),
    Rule("fio", re.compile(rf"(?<![\w\-])({_NAME})\s+({_NAME})\s+{_PATR}(?![\w\-])")),
    Rule("fio", re.compile(rf"(?<![\w\-]){_NAME}\s+{_PATR}\s+{_NAME}(?![\w\-])")),
    Rule("fio", re.compile(rf"(?<![\w\-])[{_CYR_UP}]{{2,}}\s+[{_CYR_UP}]{{2,}}\s+{_PATR_UP}(?![\w\-])")),
    Rule("fio", re.compile(rf"(?<![\w\-]){_NAME}\s+{_INI}")),
    Rule("fio", re.compile(rf"(?<![\w\-]){_INI}\s?{_NAME}(?![\w\-])")),
]


def _span(m: re.Match, rule: Rule) -> tuple[int, int]:
    if rule.group_end is not None:
        return m.start(rule.group), m.end(rule.group_end)
    return m.span(rule.group)


def _candidates(text: str, kinds: Optional[set[str]]) -> Iterator[Match]:
    for rule in RULES:
        if kinds is not None and rule.kind not in kinds:
            continue
        for m in rule.pattern.finditer(text):
            start, end = _span(m, rule)
            if rule.validate and not rule.validate(text[start:end]):
                continue
            yield Match(start, end, rule.kind)


def find_pii(text: str, kinds: Optional[set[str]] = None) -> list[Match]:
    """Возвращает непересекающиеся совпадения, отсортированные по позиции."""
    if not text or text.isspace():
        return []
    cands = sorted(_candidates(text, kinds), key=lambda m: (PRIORITY[m.kind], -(m.end - m.start), m.start))
    chosen: list[Match] = []
    for c in cands:
        if all(c.end <= o.start or c.start >= o.end for o in chosen):
            chosen.append(c)
    return sorted(chosen, key=lambda m: m.start)
