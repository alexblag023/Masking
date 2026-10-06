"""Поиск ФИО и адресов в тексте: slovnet NER + regex, с подавлением пересечений.

Правила разрешения конфликтов:
- Адрес приоритетнее ФИО (чтобы «ул. Ленина» не стала фамилией).
- Соседние PER-спаны склеиваются, если между ними только пробелы/дефисы.
- regex-находки добавляются только там, где нет пересечения с NER.
"""
import re
from dataclasses import dataclass
from typing import Optional

# Ограничиваем влияние адресного паттерна на производительность в длинных текстах.
_STREET_WORD = (
    r"(?:ул(?:ица|\.)?|пр(?:оспект|-т|-кт|\.)?|пер(?:еулок|\.)?|"
    r"наб(?:ережная|\.)?|ш(?:оссе|\.)|бул(?:ьвар|\.)?|б-р|"
    r"пл(?:ощадь|\.)?|проезд|тупик|линия|аллея|мкр(?:\.|орайон)?)"
)
_PLACE_WORD = (
    r"(?:г|гор|город|пгт|п|с|д|дер|пос|деревня|село|посёлок|поселок|хутор|ст(?:ан(?:ица)?)?)"
)
_WORD = r"[А-ЯЁ][А-Яа-яё\-]+"
_HOUSE = r"(?:(?:д|дом|корп|стр|кв|оф|офис|к|пом)\.?\s?\d+[а-яА-Я]?(?:/\d+)?)"

# Полный российский адрес с индексом/регионом/городом/улицей/домом/квартирой.
_ADDR_RE = re.compile(
    rf"""
    (?:\b\d{{6}},?\s*)?                                     # индекс
    (?:(?:{_WORD}\s+(?:область|край|округ|АО)|Республика\s+{_WORD}),?\s*)?
    (?:(?:{_PLACE_WORD})\.?\s*{_WORD}(?:[\s-]{_WORD})?,?\s*)?
    (?:{_STREET_WORD}\s*{_WORD}(?:\s+{_WORD})?(?:\s+{_STREET_WORD})?|{_WORD}\s+{_STREET_WORD})
    (?:,?\s*(?:{_HOUSE}|\d+[а-я]?(?:/\d+)?))*
    (?:,?\s*(?:{_WORD},?\s*)?\d{{6}})?
    """,
    re.VERBOSE,
)

# Короткий «г. Город, ул. Улица, дом...» без обязательной улицы.
_ADDR_CITY_RE = re.compile(
    rf"""
    (?:\b\d{{6}},?\s*)?
    г\.?\s*{_WORD}(?:[\s-]{_WORD})?
    (?:,?\s*{_STREET_WORD}\s*{_WORD}(?:\s+{_WORD})?)?
    (?:,?\s*(?:{_HOUSE}|\d+[а-я]?(?:/\d+)?))*
    """,
    re.VERBOSE,
)

# ФИО с инициалами: «Петров А.Б.» или «А.Б. Петров». NER такие пропускает.
_CYR_UP = "А-ЯЁ"
_NAME = rf"[{_CYR_UP}][а-яё]+(?:-[{_CYR_UP}][а-яё]+)?"
_INI = rf"[{_CYR_UP}]\.\s?[{_CYR_UP}]\."
_FIO_INI_RE = re.compile(
    rf"(?<![\w\-])(?:{_NAME}\s+{_INI}|{_INI}\s?{_NAME})(?![\w\-])"
)
# Полные ФИО заглавными: «ИВАНОВ ИВАН ИВАНОВИЧ». NER на капсе часто сбоит.
_FIO_UP_RE = re.compile(
    rf"(?<![\w\-])[{_CYR_UP}]{{2,}}\s+[{_CYR_UP}]{{2,}}\s+[{_CYR_UP}]+(?:ВИЧ|ВНА|ИЧНА|ЬИЧ|КЫЗЫ|ОГЛЫ|УЛЫ)(?![\w\-])"
)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str  # 'FIO' | 'ADDR'
    confidence: float = 1.0


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Отрезает хвостовые пробелы, запятые и точки, не трогая завершающий индекс/№."""
    while end > start and text[end - 1] in " ,;":
        end -= 1
    while start < end and text[start] in " ,;":
        start += 1
    return start, end


def _merge_adjacent(spans: list[tuple[int, int, str]], text: str) -> list[tuple[int, int, str]]:
    """«Петровой | Анне Сергеевне» → один спан, если между только пробелы/дефисы."""
    if not spans:
        return spans
    out = [spans[0]]
    for s, e, k in spans[1:]:
        ps, pe, pk = out[-1]
        if k == pk and 0 <= s - pe <= 2 and text[pe:s].strip(" -") == "":
            out[-1] = (ps, e, pk)
        else:
            out.append((s, e, k))
    return out


def _find_addresses(text: str) -> list[tuple[int, int]]:
    """Ищет адреса двумя regex и склеивает перекрывающиеся результаты."""
    cand = []
    for rx in (_ADDR_RE, _ADDR_CITY_RE):
        for m in rx.finditer(text):
            s, e = _trim(text, *m.span())
            if e - s >= 6:
                cand.append((s, e))
    if not cand:
        return []
    cand.sort()
    merged = [cand[0]]
    for s, e in cand[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def find_entities(text: str, ner_spans: Optional[list[tuple[int, int, str]]] = None) -> list[Span]:
    """Возвращает отсортированный список непересекающихся ФИО/адресов.

    `ner_spans` — результат masking.ner.spans(text); если None, NER не вызывается
    (удобно для юнит-тестов на regex).
    """
    if not text or text.isspace():
        return []

    addrs = _find_addresses(text)

    # ФИО от NER (PER) и наши regex. LOC из NER не используем: он слишком шумный
    # на названиях улиц и городов, которые уже покрывает адресный regex.
    fio_cand: list[tuple[int, int, str]] = []
    if ner_spans:
        per = [(s, e, "FIO") for s, e, t in ner_spans if t == "PER"]
        per = _merge_adjacent(per, text)
        fio_cand.extend(per)
    for rx in (_FIO_INI_RE, _FIO_UP_RE):
        for m in rx.finditer(text):
            s, e = _trim(text, *m.span())
            fio_cand.append((s, e, "FIO"))

    # Вычитаем ФИО, попавшие внутрь адресов.
    fio_cand = [(s, e, k) for s, e, k in fio_cand
                if not any(a0 <= s and e <= a1 for a0, a1 in addrs)]
    # Схлопываем дубли/перекрытия между regex и NER.
    fio_cand.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    fios: list[tuple[int, int, str]] = []
    for s, e, _ in fio_cand:
        if fios and s < fios[-1][1]:
            # Берём более длинный вариант.
            ps, pe, pk = fios[-1]
            if e - s > pe - ps:
                fios[-1] = (s, e, pk)
            continue
        fios.append((s, e, "FIO"))

    result = [Span(s, e, "FIO") for s, e, _ in fios]
    result += [Span(s, e, "ADDR") for s, e in addrs]
    result.sort(key=lambda x: x.start)
    return result
