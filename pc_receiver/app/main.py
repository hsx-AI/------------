from __future__ import annotations

import argparse
import getpass
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from app.api.routes import create_router
from app.config import Settings, default_config_dir, load_settings, save_shared_secret
from app.logging_config import configure_logging
from app.storage.latest_code import LatestCodeStore
from app.usb.receiver import UsbReceiverService

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, start_usb: bool = True) -> FastAPI:
    selected = settings or load_settings()
    store = LatestCodeStore(selected.code_ttl_seconds)
    usb_service = UsbReceiverService(selected, store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_usb:
            usb_service.start()
        try:
            yield
        finally:
            if start_usb:
                usb_service.stop()

    application = FastAPI(title="SMS USB Receiver", version="1.0.0", lifespan=lifespan)
    application.include_router(create_router(selected, store, usb_service))
    application.state.settings = selected
    application.state.code_store = store
    application.state.usb_service = usb_service
    return application


def command_line() -> None:
    parser = argparse.ArgumentParser(description="Android AOA SMS verification-code receiver")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="run USB receiver and local API")
    subparsers.add_parser("show-config", help="show config location and local API token")
    set_secret = subparsers.add_parser("set-secret", help="store shared HMAC secret using Windows DPAPI")
    set_secret.add_argument("--value", help="secret value; omit to enter without terminal echo")
    args = parser.parse_args()
    command = args.command or "run"

    if command == "set-secret":
        value = args.value if args.value is not None else getpass.getpass("Shared HMAC secret: ")
        path = save_shared_secret(value)
        print(f"Shared secret encrypted and saved in {path}")
        return

    settings = load_settings()
    if command == "show-config":
        print(f"Config file: {settings.config_file}")
        print(f"API token: {settings.api_token}")
        print(f"Shared secret configured: {settings.shared_secret is not None}")
        return

    configure_logging(settings.config_dir)
    if settings.shared_secret is None:
        LOGGER.warning("Shared HMAC secret is not configured; run: python -m app.main set-secret")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_config=None)


if __name__ == "__main__":
    command_line()
