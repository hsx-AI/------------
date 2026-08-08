from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Condition
from time import monotonic
from typing import Callable

from app.models.messages import CodeResponse, SmsCodeMessage


@dataclass(frozen=True)
class StoredCode:
    code: str
    sender: str
    received_at: datetime
    expires_at: datetime
    sequence: int

    def response(self) -> CodeResponse:
        return CodeResponse(code=self.code, sender=self.sender, receivedAt=self.received_at, expiresAt=self.expires_at)


class LatestCodeStore:
    def __init__(self, ttl_seconds: int = 300, now: Callable[[], datetime] | None = None):
        self._ttl = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._condition = Condition()
        self._latest: StoredCode | None = None
        self._sequence = 0

    def put(self, message: SmsCodeMessage) -> StoredCode:
        with self._condition:
            self._sequence += 1
            received = message.receivedAt
            stored = StoredCode(message.code, message.sender, received, self._now() + timedelta(seconds=self._ttl), self._sequence)
            self._latest = stored
            self._condition.notify_all()
            return stored

    def get(self, consume: bool = False) -> StoredCode | None:
        with self._condition:
            current = self._valid_latest()
            if consume and current is not None:
                self._latest = None
            return current

    def wait(self, timeout_seconds: float, sender_contains: str | None = None, after: datetime | None = None, consume: bool = True, cancel_event=None) -> StoredCode | None:
        deadline = monotonic() + timeout_seconds
        with self._condition:
            initial_sequence = self._sequence
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                current = self._valid_latest()
                is_new = current is not None and (current.sequence > initial_sequence or (after is not None and current.received_at > after))
                if is_new and current and (not sender_contains or sender_contains in current.sender) and (after is None or current.received_at > after):
                    if consume:
                        self._latest = None
                    return current
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.25) if cancel_event is not None else remaining)

    def _valid_latest(self) -> StoredCode | None:
        if self._latest and self._latest.expires_at > self._now():
            return self._latest
        self._latest = None
        return None
