"""Общая изоляция тестов: каждый тест получает свой MASKING_HOME."""
import os
import shutil
from pathlib import Path

import pytest

from masking import db


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MASKING_HOME", str(home))
    db.reset_connection()
    yield home
    db.reset_connection()
