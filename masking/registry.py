"""Операции над проектами, сущностями и историей документов."""
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import db
from .morph import match_key as fio_match_key
from .paths import files_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(name: str, maxlen: int = 60) -> str:
    """Для имён папок проектов: только буквы/цифры/_, остальное — '_'."""
    s = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_\-]+", "_", name).strip("_")
    return (s or "project")[:maxlen]


# ----- Проекты --------------------------------------------------------------

def create_project(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Название проекта пустое")
    if len(name) > 120:
        raise ValueError("Название длиннее 120 символов")
    con = db.connection()
    cur = con.execute(
        "INSERT INTO project(name, created_at) VALUES (?, ?)",
        (name, _now()),
    )
    pid = cur.lastrowid
    (files_dir() / str(pid)).mkdir(parents=True, exist_ok=True)
    return get_project(pid)


def list_projects() -> list[dict]:
    rows = db.connection().execute(
        """
        SELECT p.*,
          (SELECT COUNT(*) FROM entity   WHERE project_id = p.id) AS entities,
          (SELECT COUNT(*) FROM document WHERE project_id = p.id AND direction = 'in') AS documents,
          (SELECT MAX(created_at) FROM document WHERE project_id = p.id) AS last_activity
        FROM project p ORDER BY p.created_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_project(pid: int) -> dict:
    row = db.connection().execute(
        "SELECT * FROM project WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        raise LookupError(f"Проект {pid} не найден")
    d = dict(row)
    c = db.connection()
    d["entities"] = c.execute(
        "SELECT COUNT(*) FROM entity WHERE project_id = ?", (pid,)
    ).fetchone()[0]
    d["documents"] = c.execute(
        "SELECT COUNT(*) FROM document WHERE project_id = ? AND direction = 'in'", (pid,)
    ).fetchone()[0]
    d["occurrences"] = c.execute(
        "SELECT COUNT(*) FROM occurrence o JOIN entity e ON e.id = o.entity_id WHERE e.project_id = ?",
        (pid,),
    ).fetchone()[0]
    return d


def rename_project(pid: int, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Название проекта пустое")
    db.connection().execute("UPDATE project SET name = ? WHERE id = ?", (name, pid))
    return get_project(pid)


def delete_project(pid: int) -> None:
    get_project(pid)  # 404, если нет
    db.connection().execute("DELETE FROM project WHERE id = ?", (pid,))
    folder = files_dir() / str(pid)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


# ----- Сущности и дедупликация ---------------------------------------------

def _addr_key(text: str) -> str:
    """Нормализация адреса: lowercase, ё→е, схлопнутые пробелы, без пунктуации."""
    s = text.lower().replace("ё", "е")
    s = re.sub(r"\s+", " ", s).strip(" .,;")
    return s


def entity_key(kind: str, canonical: str, gender: Optional[str]) -> str:
    """Строковый ключ для UNIQUE(project, kind, match_key)."""
    if kind == "FIO":
        key = fio_match_key(canonical)
        return "|".join(str(x) for x in (key or (canonical.lower(),)))
    return _addr_key(canonical)


def find_or_create_entity(
    project_id: int,
    kind: str,
    canonical: str,
    gender: Optional[str] = None,
) -> dict:
    """Возвращает сущность; создаёт новую с новым seq, если ключа нет.

    seq сквозной в пределах (project, kind). Удалённые seq не переиспользуются,
    чтобы не склеить старые документы с новыми.
    """
    con = db.connection()
    key = entity_key(kind, canonical, gender)
    row = con.execute(
        "SELECT * FROM entity WHERE project_id = ? AND kind = ? AND match_key = ?",
        (project_id, kind, key),
    ).fetchone()
    if row:
        return dict(row)
    # Следующий seq — через MAX, чтобы учесть ранее удалённые записи.
    nxt = con.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM entity WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    ).fetchone()[0]
    con.execute(
        """INSERT INTO entity(project_id, kind, seq, canonical, gender, match_key, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, kind, nxt, canonical, gender, key, _now()),
    )
    row = con.execute(
        "SELECT * FROM entity WHERE project_id = ? AND kind = ? AND seq = ?",
        (project_id, kind, nxt),
    ).fetchone()
    return dict(row)


def remember_form(entity_id: int, case_code: str, surface: str) -> None:
    """Запоминаем конкретную поверхностную форму. Нужно для точного демаскирования."""
    db.connection().execute(
        "INSERT OR IGNORE INTO entity_form(entity_id, case_code, surface) VALUES (?, ?, ?)",
        (entity_id, case_code, surface),
    )


def entity_by_seq(project_id: int, kind: str, seq: int) -> Optional[dict]:
    row = db.connection().execute(
        "SELECT * FROM entity WHERE project_id = ? AND kind = ? AND seq = ?",
        (project_id, kind, seq),
    ).fetchone()
    return dict(row) if row else None


def entity_forms(entity_id: int) -> dict[str, str]:
    """{case_code: surface}. При повторах берём любую (ORDER BY id, LAST WIN)."""
    rows = db.connection().execute(
        "SELECT case_code, surface FROM entity_form WHERE entity_id = ? ORDER BY id",
        (entity_id,),
    ).fetchall()
    return {r["case_code"]: r["surface"] for r in rows}


def list_entities(
    project_id: int,
    kind: Optional[str] = None,
    query: Optional[str] = None,
) -> list[dict]:
    con = db.connection()
    sql = """
      SELECT e.*,
        (SELECT COUNT(*) FROM occurrence WHERE entity_id = e.id) AS occurrences,
        (SELECT COUNT(DISTINCT document_id) FROM occurrence WHERE entity_id = e.id) AS documents
      FROM entity e
      WHERE e.project_id = ?
    """
    args: list = [project_id]
    if kind:
        sql += " AND e.kind = ?"
        args.append(kind)
    if query:
        sql += " AND LOWER(e.canonical) LIKE ?"
        args.append(f"%{query.lower()}%")
    sql += " ORDER BY e.kind, e.seq"
    return [dict(r) for r in con.execute(sql, args).fetchall()]


# ----- История документов ---------------------------------------------------

def store_file(project_id: int, data: bytes, suffix: str) -> tuple[str, str]:
    """Сохраняет файл в data/files/<pid>/, возвращает (относительный путь, sha256)."""
    sha = hashlib.sha256(data).hexdigest()
    folder = files_dir() / str(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    # SHA в имени — дешёвая дедупликация и защита от коллизий имён файлов.
    name = f"{sha[:16]}_{datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
    path = folder / name
    path.write_bytes(data)
    return str(path.relative_to(files_dir())), sha


def add_document(
    project_id: int,
    op: str,
    direction: str,
    filename: str,
    ext: str,
    data: bytes,
    parent_id: Optional[int] = None,
    stats: Optional[dict] = None,
    warnings: Optional[dict] = None,
) -> int:
    rel, _sha = store_file(project_id, data, ext)
    cur = db.connection().execute(
        """INSERT INTO document(project_id, op, direction, parent_id, filename, ext,
                                 size, stored_path, created_at, stats_json, warnings_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, op, direction, parent_id, filename, ext, len(data), rel, _now(),
         json.dumps(stats or {}, ensure_ascii=False),
         json.dumps(warnings or {}, ensure_ascii=False)),
    )
    return cur.lastrowid


def document_data(doc_id: int) -> tuple[dict, bytes]:
    row = db.connection().execute(
        "SELECT * FROM document WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        raise LookupError(f"Документ {doc_id} не найден")
    data = (files_dir() / row["stored_path"]).read_bytes()
    return dict(row), data


def list_history(project_id: int, op: str) -> list[dict]:
    """Пары (вход, выход) по операции 'mask' или 'unmask'. Самые свежие сверху."""
    rows = db.connection().execute(
        """SELECT * FROM document
           WHERE project_id = ? AND op = ? AND direction = 'in'
           ORDER BY created_at DESC""",
        (project_id, op),
    ).fetchall()
    ins = [dict(r) for r in rows]
    for r in ins:
        out = db.connection().execute(
            "SELECT * FROM document WHERE parent_id = ? AND direction = 'out' LIMIT 1",
            (r["id"],),
        ).fetchone()
        out_d = dict(out) if out else None
        r["output"] = out_d
        # Статистику и предупреждения кладём туда, где больше: на выходном.
        src = out_d if out_d and out_d.get("stats_json") else r
        r["stats"] = json.loads(src.get("stats_json") or "{}")
        r["warnings"] = json.loads(src.get("warnings_json") or "{}")
        r.pop("stats_json", None)
        r.pop("warnings_json", None)
    return ins


def add_occurrence(entity_id: int, document_id: int, location: str, case_code: str = "nomn") -> None:
    db.connection().execute(
        "INSERT INTO occurrence(entity_id, document_id, location, case_code) VALUES (?,?,?,?)",
        (entity_id, document_id, location, case_code),
    )
