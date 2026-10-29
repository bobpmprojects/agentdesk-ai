"""SQLite connection and schema lifecycle."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(path: Path, *, recreate: bool = False) -> sqlite3.Connection:
    if recreate and path.exists():
        path.unlink()
    connection = connect(path)
    connection.executescript(SCHEMA_PATH.read_text())
    connection.commit()
    return connection
