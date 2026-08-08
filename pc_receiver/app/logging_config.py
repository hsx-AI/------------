from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Code and token values must never be passed as logging arguments.
        return True


def configure_logging(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(config_dir / "receiver.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console, file_handler], force=True)
