"""Морфология русских ФИО: падеж, пол, канонизация, склонение, ключ идентичности.

pymorphy3-анализ, с приоритетом разборов с тегами Surn/Name/Patr. Для
дефисных фамилий и несклоняемых («оглы», «кызы», «улы») — ручные правила.
"""
import itertools
import re
from functools import lru_cache
from typing import Optional

import pymorphy3

_morph = pymorphy3.MorphAnalyzer()

NAMETAGS = ("Surn", "Name", "Patr")
INVARIANT = {"оглы", "кызы", "улы"}
_WORD_RE = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)?")
_INITIAL_RE = re.compile(r"^[А-ЯЁ]\.?$")


def _cap(word: str) -> str:
    """«Иванов-петров» -> «Иванов-Петров». Регистр по частям дефисной фамилии."""
    return "-".join(part[:1].upper() + part[1:] for part in word.split("-"))


def _name_parses(word: str) -> list:
    ps = [p for p in _morph.parse(word) if any(t in p.tag for t in NAMETAGS)]
    return ps or _morph.parse(word)[:1]


def analyze(span: str) -> tuple[str, str, Optional[str]]:
    """Разбирает ФИО-строку. Возвращает (канон_имен_падеж, падеж_pm, пол или None).

    Пример: «Ивановым Иваном Ивановичем» -> ('Иванов Иван Иванович', 'ablt', 'masc').
    """
    words = _WORD_RE.findall(span)
    if not words:
        return span, "nomn", None
    opts = [_name_parses(w) for w in words]
    best = None
    for combo in itertools.product(*[o[:4] for o in opts]):
        cases = set.intersection(*[{p.tag.case} if p.tag.case else {None} for p in combo])
        case_real = cases - {None}
        genders = [p.tag.gender for p in combo if p.tag.gender]
        gagree = len(set(genders)) <= 1
        score = (bool(case_real), gagree, sum(p.score for p in combo))
        if best is None or score > best[0]:
            best = (score, combo, case_real)
    _, combo, cases = best
    case = sorted(cases)[0] if cases else "nomn"
    gender = next((p.tag.gender for p in combo if p.tag.gender), None)
    canon_parts = []
    for p, w, opt in zip(combo, words, opts):
        if w.lower() in INVARIANT:
            canon_parts.append(w.lower())
            continue
        # Выбираем разбор, у которого есть падеж, совпадающий с общим.
        # Pymorphy для «Анне» первым подсовывает несклоняемую фамилию (Fixd),
        # из-за чего inflect({"nomn"}) возвращает ту же форму. Поэтому ищем
        # разбор, в котором действительно есть падеж (не Fixd).
        pick = next(
            (q for q in opt if q.tag.case == case and "Fixd" not in q.tag),
            p,
        )
        f = pick.inflect({"nomn"})
        canon_parts.append(_cap(f.word if f else w))
    return " ".join(canon_parts), case, gender


def inflect(canon: str, case: str, gender: Optional[str] = None) -> str:
    """Склоняет каноническую (им.п.) форму ФИО в заданный падеж.

    Инициалы и слова с точкой не трогаем. Для частей дефисной фамилии
    склоняем каждую по отдельности.
    """
    if case == "nomn":
        return canon
    out = []
    for word in canon.split():
        if "." in word or word.lower() in INVARIANT or _INITIAL_RE.match(word):
            out.append(word)
            continue
        parts = []
        for sub in word.split("-"):
            candidates = [
                p for p in _morph.parse(sub)
                if any(t in p.tag for t in NAMETAGS)
                and (not gender or p.tag.gender in (gender, None))
            ] or _morph.parse(sub)
            form = None
            for p in candidates:
                form = p.inflect({case, "sing"} | ({gender} if gender else set()))
                if form:
                    break
            parts.append(form.word if form else sub)
        out.append(_cap("-".join(parts)))
    return " ".join(out)


@lru_cache(maxsize=4096)
def match_key(span: str) -> Optional[tuple]:
    """Ключ идентичности человека: не зависит от падежа и пола.

    (нормализованная_основа_фамилии, инициал_имени, инициал_отчества, пол).
    У «Иванов/Иванова/Иванову/Ивановым Иваном Ивановичем» — один ключ.
    Пол в ключе отделяет «Кравцов О.В.» от «Кравцова О.В.».
    """
    words = _WORD_RE.findall(span)
    if not words:
        return None
    surn_parses = _name_parses(words[0])
    sur = surn_parses[0].normal_form.replace("ё", "е")
    # Отрезаем словообразующие суффиксы фамилий, чтобы «Иванов/Иванова» → «иванов».
    sur = re.sub(r"(ов|ев|ин|ын|ск)(а|ая|ий|ой)?$", r"\1", sur)
    gender = next((p.tag.gender for p in surn_parses if p.tag.gender), None)
    ini = [w[0].lower() for w in words[1:]]
    while len(ini) < 2:
        ini.append(None)
    return (sur, ini[0], ini[1], gender)
