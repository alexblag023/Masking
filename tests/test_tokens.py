import re

from masking.tokens import TOKEN_RE, make_token, parse_token


def _parse(text):
    m = TOKEN_RE.search(text)
    assert m, f"не нашёл токен в {text!r}"
    return parse_token(m)


def test_make_basic():
    assert make_token("FIO", 1) == "[ФИО_1]"
    assert make_token("ADDR", 3) == "[АДРЕС_3]"
    assert make_token("FIO", 7, "datv") == "[ФИО_7:дат]"
    assert make_token("ADDR", 2, "datv") == "[АДРЕС_2]"  # у адресов падежа нет


def test_parse_strict():
    assert _parse("пример [ФИО_1] конец") == ("FIO", 1, "nomn")
    assert _parse("пример [АДРЕС_42]") == ("ADDR", 42, "nomn")
    assert _parse("[ФИО_5:дат]") == ("FIO", 5, "datv")


def test_parse_tolerant():
    """Терпимость к искажениям: пробелы, регистр, дефис/подчёркивание, полноширинные скобки."""
    for t in ["[ ФИО _ 1 ]", "[фио_1]", "[ФИО-1]", "［ФИО_1］"]:
        assert _parse(t) == ("FIO", 1, "nomn"), t


def test_unknown_is_not_matched():
    assert TOKEN_RE.search("[FOO_1]") is None
    assert TOKEN_RE.search("[ФИО1]") is None    # без разделителя
    assert TOKEN_RE.search("просто текст") is None
