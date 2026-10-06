import pytest

from masking import registry


def test_create_and_list():
    p = registry.create_project("Проект А")
    assert p["name"] == "Проект А"
    assert len(registry.list_projects()) == 1
    assert registry.get_project(p["id"])["name"] == "Проект А"


def test_duplicate_name_rejected():
    registry.create_project("Один")
    with pytest.raises(Exception):
        registry.create_project("Один")


def test_entity_dedup_by_fio_key():
    p = registry.create_project("Э")
    e1 = registry.find_or_create_entity(p["id"], "FIO", "Иванов Иван Иванович", "masc")
    e2 = registry.find_or_create_entity(p["id"], "FIO", "Иванов Иван Иванович", "masc")
    assert e1["id"] == e2["id"] == e1["id"]
    assert e1["seq"] == 1


def test_entity_seq_increments_per_kind():
    p = registry.create_project("Я")
    pid = p["id"]
    a = registry.find_or_create_entity(pid, "FIO", "Иванов Иван Иванович", "masc")
    b = registry.find_or_create_entity(pid, "FIO", "Петров Пётр Петрович", "masc")
    c = registry.find_or_create_entity(pid, "ADDR", "г. Москва, ул. Ленина, д. 5", None)
    assert (a["seq"], b["seq"], c["seq"]) == (1, 2, 1)


def test_delete_cascades():
    p = registry.create_project("Для удаления")
    pid = p["id"]
    registry.find_or_create_entity(pid, "FIO", "Иванов Иван Иванович", "masc")
    registry.add_document(pid, "mask", "in", "x.docx", ".docx", b"ab")
    assert registry.get_project(pid)["entities"] == 1
    registry.delete_project(pid)
    with pytest.raises(LookupError):
        registry.get_project(pid)
    # Второй проект с тем же именем создаётся без конфликта.
    registry.create_project("Для удаления")
