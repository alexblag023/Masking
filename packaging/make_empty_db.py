"""Создать ПУСТУЮ рабочую базу masking.db для поставки (product-ready пакет).

Инициализирует схему приложения (project, document, entity, entity_form,
occurrence) без единой строки данных, схлопывает WAL в один файл.

    python packaging/make_empty_db.py <путь к masking.db>
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# UTF-8 stdout: скрипт запускается subprocess'ом и print с кириллицей
# иначе падает на Windows (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from masking import db  # noqa: E402


def make_empty_db(dest: Path) -> None:
    dest = Path(dest)
    for suffix in ("", "-wal", "-shm"):
        p = dest.with_name(dest.name + suffix)
        p.unlink(missing_ok=True)
    # db.connection() сам создаст и применит SCHEMA. Указываем путь через env.
    os.environ["MASKING_HOME"] = str(dest.parent.parent)   # data_dir = <home>/data
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Делаем подмену: кладём напрямую в указанный путь, не через paths.db_path().
    db.reset_connection()
    con = sqlite3.connect(str(dest), isolation_level=None)
    con.executescript(db.SCHEMA)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("использование: make_empty_db.py <путь к masking.db>")
    make_empty_db(Path(sys.argv[1]))
    print(f"пустая база создана: {sys.argv[1]}")
