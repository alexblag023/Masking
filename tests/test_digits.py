"""Числовая маска: распознанные типы + универсальный DIGITS."""
import pytest

from masking.digits import find_digit_spans, inn_ok, luhn_ok, snils_ok


def kinds(text):
    return [(text[s:e], k) for s, e, k in find_digit_spans(text)]


def test_checksums():
    assert inn_ok("500100732259") and not inn_ok("500100732258")
    assert inn_ok("7707083893")
    assert snils_ok("112-233-445 95")
    assert luhn_ok("4111 1111 1111 1111")


@pytest.mark.parametrize("text,expected", [
    ("тел +7 916 123-45-67", ("+7 916 123-45-67", "PHONE")),
    ("СНИЛС 112-233-445 95", ("112-233-445 95", "SNILS")),
    ("ИНН 500100732259", ("500100732259", "INN")),
    ("карта 4111 1111 1111 1111", ("4111 1111 1111 1111", "CARD")),
    ("паспорт 45 06 123456", ("45 06 123456", "PASSPORT")),
    ("дата рождения 01.02.1990", ("01.02.1990", "DATE")),
    ("email ivan@mail.ru", ("ivan@mail.ru", "EMAIL")),
])
def test_recognized_types(text, expected):
    assert expected in kinds(text)


def test_digits_fallback_catches_unknown_numbers():
    """Номера домов, кабинетов, индексы — всё что не подошло к известному типу."""
    text = "кабинет 305, корп. 12, индекс 123456"
    found = kinds(text)
    assert ("305", "DIGITS") in found
    assert ("12", "DIGITS") in found
    assert ("123456", "DIGITS") in found


def test_single_digit_not_masked():
    """Одиночная цифра — слишком шумно, не трогаем."""
    assert kinds("дом 5") == []


def test_digits_do_not_overlap_recognized():
    """ИНН 500100732259 не должен ещё раз попасть в DIGITS."""
    out = kinds("ИНН 500100732259 договор")
    assert ("500100732259", "DIGITS") not in out
    assert ("500100732259", "INN") in out
