import pytest

from masking.morph import analyze, inflect, match_key


@pytest.mark.parametrize("span,canon,case,gender", [
    ("Ивановым Иваном Ивановичем", "Иванов Иван Иванович", "ablt", "masc"),
    ("Иванова Ивана Ивановича",    "Иванов Иван Иванович", "gent", "masc"),
    ("Иванову Ивану Ивановичу",    "Иванов Иван Иванович", "datv", "masc"),
    ("Петровой Анне Сергеевне",    "Петрова Анна Сергеевна", "datv", "femn"),
    ("Петровой Анны Сергеевны",    "Петрова Анна Сергеевна", "gent", "femn"),
    ("Шевченко Тарасу Григорьевичу", "Шевченко Тарас Григорьевич", "datv", "masc"),
])
def test_analyze(span, canon, case, gender):
    c, cs, g = analyze(span)
    assert (c.replace("ё", "е"), cs, g) == (canon.replace("ё", "е"), case, gender)


@pytest.mark.parametrize("canon,case,gender,expected", [
    ("Иванов Иван Иванович", "datv", "masc", "Иванову Ивану Ивановичу"),
    ("Иванов Иван Иванович", "ablt", "masc", "Ивановым Иваном Ивановичем"),
    ("Петрова Анна Сергеевна", "datv", "femn", "Петровой Анне Сергеевне"),
    ("Петрова Анна Сергеевна", "gent", "femn", "Петровой Анны Сергеевны"),
    ("Иванов Иван Иванович", "nomn", "masc", "Иванов Иван Иванович"),
])
def test_inflect(canon, case, gender, expected):
    assert inflect(canon, case, gender).replace("ё", "е") == expected.replace("ё", "е")


def test_match_key_merges_forms():
    k = match_key("Ивановым Иваном Ивановичем")
    for s in ("Иванов Иван Иванович", "Иванова Ивана Ивановича", "Иванову Ивану Ивановичу"):
        assert match_key(s) == k


def test_match_key_separates_relatives():
    """Разный пол → разные ключи, даже при одинаковой фамилии и инициалах."""
    k1 = match_key("Кравцов Олег Васильевич")
    k2 = match_key("Кравцова Ольга Васильевна")
    assert k1 != k2
