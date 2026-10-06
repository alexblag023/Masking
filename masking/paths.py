"""Определение путей в portable-режиме: все данные лежат рядом с exe."""
import os
import sys
from pathlib import Path


def base_dir() -> Path:
    """Папка, рядом с которой хранятся данные.

    Для собранного exe (PyInstaller) — папка с исполняемым файлом.
    В обычном запуске — корень репозитория (на уровень выше пакета).
    Переопределяется переменной окружения MASKING_HOME.
    """
    env = os.environ.get("MASKING_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = base_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def files_dir() -> Path:
    d = data_dir() / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "masking.db"


def models_dir() -> Path:
    """Папка с моделями NER. Внутри пакета (бандлится в exe как data)."""
    return Path(__file__).resolve().parent / "models"


def port_file() -> Path:
    """Файл с текущим портом сервиса (пишется при старте, читается установщиком)."""
    return data_dir() / ".port"


def writable_check() -> str | None:
    """Проверяет, что в папку данных можно писать. Возвращает текст ошибки или None."""
    try:
        probe = data_dir() / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return None
    except OSError as exc:
        return (
            f"Папка данных недоступна для записи: {data_dir()}\n{exc}\n"
            "Скопируйте программу в папку, где разрешена запись, "
            "или задайте путь через переменную MASKING_HOME."
        )
