"""Тесты установщика: разбор compat.txt, сравнение версий, тихий install.

Запускаем без Windows-специфики (без tkinter.mainloop, без winreg).
"""
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import installer_app as inst  # noqa: E402


def test_parse_compat():
    assert inst._parse_compat("schema=2\nmin_compat=1\nversion=2026.10.3\n") == {
        "schema": 2, "min_compat": 1, "version": "2026.10.3",
    }
    assert inst._parse_compat("") == {"schema": 1, "min_compat": 1, "version": ""}


@pytest.mark.parametrize("a,b,expected", [
    ("2026.10.3", "2026.10.1", 1),
    ("2026.10.1", "2026.10.3", -1),
    ("2026.10.1", "2026.10.1", 0),
    ("2026.11", "2026.10.9", 1),
])
def test_cmp_ver(a, b, expected):
    assert inst._cmp_ver(a, b) == expected


def _make_fake_package(tmp: Path, version: str, schema: int = 1, min_compat: int = 1) -> Path:
    """Собирает минимальный zip-пакет Masking/ для тестов install."""
    # Каждая версия стейджится в отдельной папке, чтобы разные вызовы в одном
    # тесте не конфликтовали.
    # Уникально по версии+схеме+попытке — на случай повторного вызова.
    i = 0
    while True:
        stage = tmp / f"stage_{version}_{schema}_{i}"
        if not stage.exists():
            break
        i += 1
    pkg = stage / "Masking"
    pkg.mkdir(parents=True)
    (pkg / "masking-service.exe").write_bytes(b"MZ fake exe v" + version.encode())
    internal = pkg / "_internal"
    internal.mkdir()
    (internal / "lib.dll").write_bytes(b"fake dll")
    (pkg / "data").mkdir()
    (pkg / "data" / "masking.db").write_bytes(b"SQLite empty")
    (pkg / "compat.txt").write_text(
        f"schema={schema}\nmin_compat={min_compat}\nversion={version}\n", encoding="utf-8")
    (pkg / "README_оператор.txt").write_text("test", encoding="utf-8")
    zip_path = tmp / f"Masking_{version}_{schema}_{i}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for p in stage.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(stage))
    return zip_path


def test_install_fresh(tmp_path, monkeypatch):
    zip_path = _make_fake_package(tmp_path, "2026.10.1")
    monkeypatch.setenv("MASKING_INSTALLER_ZIP", str(zip_path))
    target = tmp_path / "install_target"
    target.mkdir()
    msg = inst.do_install(str(target))
    assert "Установка" in msg
    installed = target / "Masking"
    assert (installed / "masking-service.exe").is_file()
    assert (installed / "data" / "masking.db").is_file()
    assert (installed / "compat.txt").read_text(encoding="utf-8").startswith("schema=1")


def test_update_preserves_data(tmp_path, monkeypatch):
    # 1) Ставим v1, пишем «пользовательский» файл в data/.
    zip_v1 = _make_fake_package(tmp_path, "2026.10.1", schema=1)
    monkeypatch.setenv("MASKING_INSTALLER_ZIP", str(zip_v1))
    target = tmp_path / "install_target"
    target.mkdir()
    inst.do_install(str(target))
    (target / "Masking" / "data" / "my_project_file.txt").write_text("user data", encoding="utf-8")
    # 2) Ставим v2 поверх — файл в data/ должен сохраниться.
    zip_v2 = _make_fake_package(tmp_path, "2026.10.2", schema=1)
    monkeypatch.setenv("MASKING_INSTALLER_ZIP", str(zip_v2))
    msg = inst.do_install(str(target))
    assert "Обновление" in msg
    assert (target / "Masking" / "data" / "my_project_file.txt").read_text(encoding="utf-8") == "user data"
    assert "2026.10.2" in (target / "Masking" / "compat.txt").read_text(encoding="utf-8")


def test_downgrade_without_consent_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("MASKING_INSTALLER_ZIP", str(_make_fake_package(tmp_path, "2026.10.3")))
    target = tmp_path / "t"; target.mkdir()
    inst.do_install(str(target))
    monkeypatch.setenv("MASKING_INSTALLER_ZIP", str(_make_fake_package(tmp_path, "2026.10.1")))
    msg = inst.do_install(str(target), confirm=lambda _: False)
    assert msg.startswith("Отменено")
    # Версия не изменилась.
    assert "2026.10.3" in (target / "Masking" / "compat.txt").read_text(encoding="utf-8")


def test_incompatible_schema_full_reinstall_with_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("MASKING_INSTALLER_ZIP",
                        str(_make_fake_package(tmp_path, "2026.10.1", schema=1)))
    target = tmp_path / "t"; target.mkdir()
    inst.do_install(str(target))
    (target / "Masking" / "data" / "important.txt").write_text("x", encoding="utf-8")
    # Новая версия со сломанной обратной совместимостью.
    monkeypatch.setenv("MASKING_INSTALLER_ZIP",
                        str(_make_fake_package(tmp_path, "2026.11.1", schema=2, min_compat=2)))
    msg = inst.do_install(str(target), allow_downgrade=True)
    assert "полная переустановка" in msg
    # Бэкап появился.
    backups = [p for p in target.iterdir() if p.name.startswith("Masking_backup_")]
    assert backups
    # data/ перенеслась.
    assert (target / "Masking" / "data" / "important.txt").read_text(encoding="utf-8") == "x"


def test_preview_action(tmp_path, monkeypatch):
    monkeypatch.setenv("MASKING_INSTALLER_ZIP",
                        str(_make_fake_package(tmp_path, "2026.10.1")))
    target = tmp_path / "t"; target.mkdir()
    assert "Будет установлено" in inst.preview_action(str(target))
    inst.do_install(str(target))
    monkeypatch.setenv("MASKING_INSTALLER_ZIP",
                        str(_make_fake_package(tmp_path, "2026.10.1")))
    assert "переустановка" in inst.preview_action(str(target))
    monkeypatch.setenv("MASKING_INSTALLER_ZIP",
                        str(_make_fake_package(tmp_path, "2026.11.1")))
    assert "обновление" in inst.preview_action(str(target)).lower()


def test_stop_running_app_noop_when_not_running(tmp_path):
    """Если exe не занят — stop_running_app сразу True, ничего не ломает."""
    (tmp_path / "masking-service.exe").write_bytes(b"MZ fake")
    assert inst.stop_running_app(str(tmp_path), log=lambda *_: None) is True


def test_read_port_from_data_dir(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".port").write_text("12345", encoding="utf-8")
    assert inst._read_port(str(tmp_path)) == 12345
    (tmp_path / "data" / ".port").write_text("not-a-number")
    assert inst._read_port(str(tmp_path)) is None
    (tmp_path / "data" / ".port").unlink()
    assert inst._read_port(str(tmp_path)) is None
