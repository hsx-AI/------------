from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.messages import SmsCodeMessage


TOKEN = "t" * 32


def test_health_and_authorization():
    app = create_app(Settings(Path("."), TOKEN, b"secret"), start_usb=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/latest-code").status_code == 401


def test_dashboard_is_local_secure_html():
    app = create_app(Settings(Path("."), TOKEN, b"secret"), start_usb=False)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "SMS USB Receiver" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.cookies.get("smsusb_session")
        assert client.get("/api/latest-code").status_code == 404


def test_latest_code_can_be_consumed():
    app = create_app(Settings(Path("."), TOKEN, b"secret"), start_usb=False)
    now = datetime.now(timezone.utc)
    app.state.code_store.put(SmsCodeMessage(protocolVersion=1, messageId=uuid4(), type="sms_code", sender="1069", code="583921", smsTextMasked="58****", receivedAt=now, sentAt=now, nonce="abcdefghijklmnop", hmac="0" * 64))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        response = client.get("/api/latest-code?consume=true", headers=headers)
        assert response.status_code == 200 and response.json()["code"] == "583921"
        assert client.get("/api/latest-code", headers=headers).status_code == 404


def test_wait_timeout_returns_408():
    app = create_app(Settings(Path("."), TOKEN, b"secret"), start_usb=False)
    with TestClient(app) as client:
        response = client.post("/api/wait-code", headers={"Authorization": f"Bearer {TOKEN}"}, json={"timeoutSeconds": 1})
        assert response.status_code == 408
