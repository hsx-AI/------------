from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEDULER_CONFIG = ROOT / "scheduler_config.json"
DEFAULT_DB = ROOT / "data" / "ecs_documents.db"


def load_scheduler_config(path: Path | None = None) -> dict:
    config_path = path or DEFAULT_SCHEDULER_CONFIG
    if not config_path.exists():
        return {
            "intervalMinutes": 60,
            "runImmediately": True,
            "dbPath": str(DEFAULT_DB.relative_to(ROOT)).replace("\\", "/"),
            "keepDownloadedExcel": True,
            "preferSavedSession": True,
        }
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("scheduler_config.json 顶层必须是 JSON 对象")
    return data


def resolve_db_path(config: dict) -> Path:
    raw = str(config.get("dbPath", DEFAULT_DB)).strip() or str(DEFAULT_DB)
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path
