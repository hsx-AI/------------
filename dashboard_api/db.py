from __future__ import annotations

import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "ecs_documents.db"


def resolve_db_path() -> Path:
    raw = os.environ.get("ECS_DB_PATH", "").strip()
    path = Path(raw) if raw else DEFAULT_DB
    if not path.is_absolute():
        path = ROOT / path
    return path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or resolve_db_path()
    if not path.exists():
        raise FileNotFoundError(f"找不到数据库: {path}")
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
