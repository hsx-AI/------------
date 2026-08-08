from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json

import pytest

from app.config import Settings
from app.security.hmac_utils import generate_hmac
from app.storage.latest_code import LatestCodeStore
from app.usb.receiver import MessageProcessor


def signed(secret=b"shared-secret", nonce="abcdefghijklmnop", message_id=None):
    now = datetime.now(timezone.utc).isoformat()
    data = {"protocolVersion": 1, "messageId": str(message_id or uuid4()), "type": "sms_code", "sender": "10690000", "code": "583921", "smsTextMasked": "验证码 58****", "receivedAt": now, "sentAt": now, "nonce": nonce, "hmac": ""}
    data["hmac"] = generate_hmac(data, secret)
    return data


def processor():
    settings = Settings(Path("."), "x" * 32, b"shared-secret")
    store = LatestCodeStore()
    return MessageProcessor(settings, store), store


def test_accepts_and_stores_valid_message():
    subject, store = processor()
    data = signed()
    ack = subject.process(json.dumps(data, ensure_ascii=False))
    assert str(ack.messageId) == data["messageId"]
    assert store.get().code == "583921"


def test_duplicate_message_id_gets_idempotent_ack_without_overwrite():
    subject, store = processor()
    data = signed()
    subject.process(json.dumps(data))
    subject.process(json.dumps(data))
    assert store.get().code == "583921"


def test_replayed_nonce_with_new_id_is_rejected():
    subject, _ = processor()
    subject.process(json.dumps(signed(nonce="same-nonce-12345")))
    with pytest.raises(ValueError, match="replayed nonce"):
        subject.process(json.dumps(signed(nonce="same-nonce-12345")))


def test_tampered_code_is_rejected():
    subject, store = processor()
    data = signed(); data["code"] = "000000"
    with pytest.raises(ValueError, match="HMAC"):
        subject.process(json.dumps(data))
    assert store.get() is None
