from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping

from app.models.messages import SmsCodeMessage


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Match Android's sorted, compact, UTF-8 JSON canonicalization."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def signing_payload(message: SmsCodeMessage | Mapping[str, Any]) -> bytes:
    if isinstance(message, SmsCodeMessage):
        data = message.model_dump(mode="json")
    else:
        data = dict(message)
    data.pop("hmac", None)
    return canonical_json_bytes(data)


def generate_hmac(message: SmsCodeMessage | Mapping[str, Any], secret: bytes) -> str:
    if not secret:
        raise ValueError("shared secret is empty")
    return hmac.new(secret, signing_payload(message), hashlib.sha256).hexdigest()


def verify_hmac(message: SmsCodeMessage | Mapping[str, Any], secret: bytes) -> bool:
    supplied = message.hmac if isinstance(message, SmsCodeMessage) else message.get("hmac")
    return isinstance(supplied, str) and hmac.compare_digest(generate_hmac(message, secret), supplied)
