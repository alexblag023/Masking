import pytest

from masking.entities import find_entities


def kinds(text, ner=None):
    return [(text[s.start:s.end], s.kind) for s in find_entities(text, ner)]


@pytest.mark.parametrize("text,expected", [
    ("подпись Петров А.Б.", ("Петров А.Б.", "FIO")),
    ("А.Б. Петров подписал", ("А.Б. Петров", "FIO")),
    ("ИВАНОВ ИВАН ИВАНОВИЧ", ("ИВАНОВ ИВАН ИВАНОВИЧ", "FIO")),
])
def test_regex_fio_no_ner(text, expected):
    """Инициалы и капс — только regex, без NER."""
    assert expected in kinds(text)


def test_addresses():
    text = "Адрес: г. Москва, ул. Ленина, д. 5, кв. 12."
    assert ("г. Москва, ул. Ленина, д. 5, кв. 12", "ADDR") in kinds(text)


def test_address_wins_over_fio_regex():
    """«ул. Ленина» не должна стать фамилией."""
    text = "адрес ул. Ленина, д. 3"
    found = kinds(text)
    assert all(k != "FIO" for _, k in found)


def test_ner_person_integrates():
    # Эмулируем NER-ответ, чтобы тест был быстрым и детерминированным.
    text = "Договор с Ивановым Иваном Ивановичем на сумму..."
    ner = [(10, 36, "PER")]
    assert ("Ивановым Иваном Ивановичем", "FIO") in kinds(text, ner)


def test_adjacent_per_spans_merge():
    text = "Петровой Анне Сергеевне передано"
    ner = [(0, 8, "PER"), (9, 23, "PER")]
    found = kinds(text, ner)
    assert any(s == "Петровой Анне Сергеевне" and k == "FIO" for s, k in found)


def test_duplicate_fio_from_ner_and_regex_dedup():
    text = "подпись: Петров А.Б."
    ner = [(9, 15, "PER")]  # "Петров" из NER
    out = kinds(text, ner)
    # Остаётся один ФИО (regex-находка длиннее).
    fios = [x for x in out if x[1] == "FIO"]
    assert len(fios) == 1 and fios[0][0] == "Петров А.Б."
