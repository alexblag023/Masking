"""Версия приложения и схемы данных.

Формат версии — ГОД.МЕСЯЦ.ПОРЯДКОВЫЙ: оператору/коллеге дата понятнее semver.

К версии добавляется отметка сборки (хэш коммита): две сборки с одним номером,
но из разных коммитов, иначе было бы не различить. Скрипт сборки
packaging/build.py пишет build_stamp.py; в dev-запуске хэш берётся из git.
"""
from __future__ import annotations

VERSION = "2026.10.1"

# Версия схемы SQLite (masking.db). Поднимается при НЕсовместимом изменении,
# которое миграция не отыграет вперёд. Пока одна схема — обе равны.
SCHEMA_VERSION = 1
MIN_COMPAT_SCHEMA = 1


def _build_stamp() -> str:
    """Короткий хэш коммита сборки; при незакоммиченных правках — с пометкой."""
    try:
        from build_stamp import BUILD_STAMP   # пишется packaging/build.py
        return BUILD_STAMP
    except Exception:
        try:
            import subprocess
            from pathlib import Path
            root = Path(__file__).resolve().parent.parent
            rev = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            return (rev + ("+изменения" if dirty else "")) or "dev"
        except Exception:
            return "dev"


def full_version() -> str:
    """«2026.10.1 (abcdef0)» — показывается в UI и заголовке."""
    return f"{VERSION} ({_build_stamp()})"
