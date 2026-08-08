from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    api_token: str
    shared_secret: bytes | None
    host: str = "127.0.0.1"
    port: int = 8765
    code_ttl_seconds: int = 300
    max_message_age_seconds: int = 600
    future_skew_seconds: int = 60
    usb_read_timeout_ms: int = 1000

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_Blob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_secret(secret: bytes) -> str:
    if os.name != "nt":
        raise RuntimeError("persistent shared-secret storage requires Windows DPAPI")
    source, keepalive = _blob(secret)
    output = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "SmsUsbForwarder", None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return base64.b64encode(ctypes.string_at(output.pbData, output.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def unprotect_secret(value: str) -> bytes:
    source, keepalive = _blob(base64.b64decode(value, validate=True))
    output = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def default_config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "SmsUsbForwarder"


def _restrict_acl(path: Path) -> None:
    if os.name != "nt":
        return
    username = os.environ.get("USERNAME")
    if not username:
        return
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(F)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    _restrict_acl(path.parent)
    _restrict_acl(path)


def load_settings(config_dir: Path | None = None) -> Settings:
    directory = config_dir or default_config_dir()
    path = directory / "config.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"apiToken": secrets.token_urlsafe(32), "sharedSecretProtected": None, "port": 8765}
        _write(path, data)
    token = data.get("apiToken")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError(f"invalid apiToken in {path}")
    env_secret = os.environ.get("SMSUSB_SHARED_SECRET")
    protected = data.get("sharedSecretProtected")
    secret = env_secret.encode("utf-8") if env_secret is not None else unprotect_secret(protected) if protected else None
    return Settings(config_dir=directory, api_token=token, shared_secret=secret, port=int(data.get("port", 8765)))


def save_shared_secret(secret: str, config_dir: Path | None = None) -> Path:
    if not secret:
        raise ValueError("shared secret cannot be empty")
    directory = config_dir or default_config_dir()
    path = directory / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"apiToken": secrets.token_urlsafe(32), "port": 8765}
    data["sharedSecretProtected"] = protect_secret(secret.encode("utf-8"))
    _write(path, data)
    return path
