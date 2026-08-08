from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from time import sleep
from typing import Callable

from pydantic import ValidationError
import usb.core

from app.config import Settings
from app.models.messages import AckMessage, SmsCodeMessage
from app.security.hmac_utils import verify_hmac
from app.security.replay_guard import ReplayGuard
from app.storage.latest_code import LatestCodeStore
from app.usb.aoa import find_aoa_device, open_aoa_device, switch_first_supported_device, wait_for_aoa
from app.usb.protocol import ProtocolError, encode_frame
from app.usb.transport import UsbTransport

LOGGER = logging.getLogger(__name__)


class MessageProcessor:
    def __init__(self, settings: Settings, store: LatestCodeStore):
        self._settings = settings
        self._store = store
        self._nonces = ReplayGuard(settings.max_message_age_seconds)
        self._message_ids = ReplayGuard(settings.max_message_age_seconds)

    def process(self, text: str) -> AckMessage:
        if self._settings.shared_secret is None:
            raise ValueError("shared secret is not configured")
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("JSON root must be an object")
        message = SmsCodeMessage.model_validate(raw)
        if not verify_hmac(raw, self._settings.shared_secret):
            raise ValueError("invalid HMAC")
        now = datetime.now(timezone.utc)
        sent_at = message.sentAt.astimezone(timezone.utc)
        age = (now - sent_at).total_seconds()
        if age > self._settings.max_message_age_seconds or age < -self._settings.future_skew_seconds:
            raise ValueError("message timestamp outside allowed window")
        message_id = str(message.messageId)
        if self._message_ids.contains(message_id):
            return self._ack(message)
        if not self._nonces.accept(message.nonce):
            raise ValueError("replayed nonce")
        if not self._message_ids.accept(message_id):
            return self._ack(message)
        self._store.put(message)
        LOGGER.info("Accepted SMS code from sender %s ending in **%s", message.sender, message.code[-2:])
        return self._ack(message)

    @staticmethod
    def _ack(message: SmsCodeMessage) -> AckMessage:
        return AckMessage(messageId=message.messageId, receivedAt=datetime.now(timezone.utc))


class UsbReceiverService:
    def __init__(self, settings: Settings, store: LatestCodeStore):
        self._settings = settings
        self._processor = MessageProcessor(settings, store)
        self._stop = Event()
        self._thread: Thread | None = None
        self._state_lock = Lock()
        self._connected = False
        self.last_message_at: datetime | None = None

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return self._connected

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="aoa-usb-receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _set_connected(self, value: bool) -> None:
        with self._state_lock:
            self._connected = value

    def _run(self) -> None:
        while not self._stop.is_set():
            transport: UsbTransport | None = None
            try:
                device = find_aoa_device()
                if device is None:
                    if switch_first_supported_device():
                        device = wait_for_aoa(10)
                    if device is None:
                        self._stop.wait(2)
                        continue
                transport = UsbTransport(open_aoa_device(device), self._settings.usb_read_timeout_ms)
                self._set_connected(True)
                LOGGER.info("AOA USB accessory connected")
                for text in transport.read_frames(self._stop.is_set):
                    try:
                        ack = self._processor.process(text)
                        payload = ack.model_dump(mode="json")
                        transport.write(encode_frame(payload))
                        self.last_message_at = datetime.now(timezone.utc)
                    except (ValueError, ValidationError, ProtocolError, json.JSONDecodeError) as exc:
                        # ValidationError text can echo input fields, including the code.
                        LOGGER.warning("Rejected USB message (%s)", type(exc).__name__)
            except (usb.core.USBError, OSError, RuntimeError, ProtocolError) as exc:
                LOGGER.warning("USB session ended: %s", exc)
            except Exception:
                LOGGER.exception("Unexpected USB worker error")
            finally:
                self._set_connected(False)
                if transport is not None:
                    transport.close()
            self._stop.wait(1)
