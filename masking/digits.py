"""Поиск чисел для обратимого маскирования.

Трендовый подход: format-preserving tokenization. Распознаём известные типы
ПДн (телефон, СНИЛС, ИНН, карта, паспорт, email, дата, 6-значный индекс)
по regex с проверкой контрольных сумм, а всё остальное — универсальный
«ЦИФ_N» (цифровые группы длиной ≥ 2 после границы слова).

Одиночные цифры не трогаем: это обычно нумерация пунктов, этажи, количества,
их маскировка превращает документ в кашу без пользы для анонимизации.
"""
import re
from dataclasses import dataclass

# ---- Контрольные суммы ---------------------------------------------------

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
    check = 0 if total in (100, 101) else total if total < 100 else total % 101
    if check in (100, 101):
        check = 0
    return check == d[9] * 10 + d[10]


# ---- Правила -----------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    kind: str                            # 'PHONE' | 'SNILS' | ...
    pattern: re.Pattern
    group: int = 0
    group_end: int | None = None
    validate: callable = None


RULES = [
    # Сначала самые специфичные — чтобы они перехватили до универсального DIGITS.
    Rule("CARD", re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), validate=luhn_ok),
    Rule("SNILS", re.compile(r"(?<!\d)\d{3}[\- ]\d{3}[\- ]\d{3}[ \-]\d{2}(?!\d)"), validate=snils_ok),
    Rule("SNILS", re.compile(r"(?i)снилс[^\d]{0,15}(\d{11})(?!\d)"), group=1, validate=snils_ok),
    Rule("EMAIL", re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")),
    Rule("PHONE", re.compile(
        r"(?<![\w+])(?:\+7|[78])[\s\-]*\(?\d{3}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")),
    # 12 цифр подряд с проверкой — ИНН физлица.
    Rule("INN", re.compile(r"(?<!\d)\d{12}(?!\d)"), validate=inn_ok),
    Rule("INN", re.compile(r"(?i)инн[^\d]{0,15}(\d{10}|\d{12})(?!\d)"), group=1, validate=inn_ok),
    Rule("PASSPORT", re.compile(
        r"(?i)паспорт[^\d]{0,40}(\d{2}\s?\d{2}[\s,№N-]{0,3}\d{6})(?!\d)"), group=1),
    Rule("PASSPORT", re.compile(
        r"(?i)серия[^\d]{0,5}(\d{2}\s?\d{2})\s*(?:№|номер|N)?\s*(\d{6})(?!\d)"),
        group=1, group_end=2),
    Rule("DATE", re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}[./]\d{2,4}(?!\d)")),
    # Универсальный фоллбек: группа из 2+ цифр, не часть большего числа.
    Rule("DIGITS", re.compile(r"(?<!\d)\d{2,}(?!\d)")),
]


def _span(m: re.Match, rule: Rule) -> tuple[int, int]:
    if rule.group_end is not None:
        return m.start(rule.group), m.end(rule.group_end)
    return m.span(rule.group)


def find_digit_spans(text: str, kinds: set[str] | None = None) -> list[tuple[int, int, str]]:
    """Возвращает [(start, end, kind), ...] непересекающиеся, отсортированные.

    Приоритет — порядок RULES: распознанный тип побеждает DIGITS. Если указан
    фильтр `kinds`, оставляем только эти типы (но для подавления пересечений
    всё равно просматриваем всё — иначе CARD не вытеснит DIGITS).
    """
    if not text or text.isspace():
        return []
    taken: list[tuple[int, int, str]] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            s, e = _span(m, rule)
            if rule.validate and not rule.validate(text[s:e]):
                continue
            # Проверяем пересечение с уже выбранными — пропускаем, если накладывается.
            if any(not (e <= ps or s >= pe) for ps, pe, _ in taken):
                continue
            taken.append((s, e, rule.kind))
    taken.sort()
    if kinds is not None:
        taken = [t for t in taken if t[2] in kinds]
    return taken
