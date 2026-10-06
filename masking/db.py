"""SQLite-хранилище: соединение, схема, подключение, миграции.

Один файл masking.db рядом с exe. Открывается с WAL (устойчив к падениям,
даёт параллельное чтение), один писатель — сервис в одном процессе.
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS project(
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  archived   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document(
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  op          TEXT NOT NULL CHECK(op IN ('mask','unmask')),
  direction   TEXT NOT NULL CHECK(direction IN ('in','out')),
  parent_id   INTEGER REFERENCES document(id) ON DELETE SET NULL,
  filename    TEXT NOT NULL,
  ext         TEXT NOT NULL,
  size        INTEGER NOT NULL,
  stored_path TEXT NOT NULL,         -- относительно data/files/<project_id>/
  created_at  TEXT NOT NULL,
  stats_json  TEXT,
  warnings_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_proj ON document(project_id, op, created_at DESC);

CREATE TABLE IF NOT EXISTS entity(
  id         INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK(kind IN ('FIO','ADDR')),
  seq        INTEGER NOT NULL,
  canonical  TEXT NOT NULL,          -- ФИО в им. п. / адрес как встретился
  gender     TEXT,                   -- 'masc' | 'femn' | NULL
  match_key  TEXT NOT NULL,          -- ключ дедупликации в рамках (project, kind)
  excluded   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, kind, seq),
  UNIQUE(project_id, kind, match_key)
);

CREATE TABLE IF NOT EXISTS entity_form(
  id         INTEGER PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  case_code  TEXT NOT NULL,          -- 'nomn' | 'gent' | ...
  surface    TEXT NOT NULL,          -- именно в этой форме слово встречено
  UNIQUE(entity_id, case_code, surface)
);

CREATE TABLE IF NOT EXISTS occurrence(
  id          INTEGER PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  location    TEXT NOT NULL,         -- 'docx:body/p12' | 'xlsx:Лист1!B7'
  case_code   TEXT NOT NULL DEFAULT 'nomn'
);
CREATE INDEX IF NOT EXISTS ix_occ_ent ON occurrence(entity_id);
CREATE INDEX IF NOT EXISTS ix_occ_doc ON occurrence(document_id);

CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version(version) VALUES (1);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_db_path_cached: Path | None = None


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.executescript(SCHEMA)
    return con


def connection() -> sqlite3.Connection:
    """Единое соединение процесса. Переоткрывается, если изменился путь к БД."""
    global _conn, _db_path_cached
    with _lock:
        path = db_path()
        if _conn is None or _db_path_cached != path:
            if _conn is not None:
                _conn.close()
            _conn = _connect(path)
            _db_path_cached = path
        return _conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Транзакция. Всё внутри одного BEGIN/COMMIT."""
    con = connection()
    with _lock:
        con.execute("BEGIN")
        try:
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def reset_connection() -> None:
    """Закрыть кэшированное соединение (тесты меняют MASKING_HOME)."""
    global _conn, _db_path_cached
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _db_path_cached = None
