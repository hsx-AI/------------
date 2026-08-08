from __future__ import annotations

import logging
from threading import Lock

import usb.core

from app.usb.aoa import AoaConnection
from app.usb.protocol import FrameDecoder

LOGGER = logging.getLogger(__name__)


class UsbTransport:
    def __init__(self, connection: AoaConnection, read_timeout_ms: int = 1000):
        self._connection = connection
        self._read_timeout = read_timeout_ms
        self._write_lock = Lock()
        self._closed = False

    def read_frames(self, stop_requested) -> list[str]:
        decoder = FrameDecoder()
        while not stop_requested():
            try:
                chunk = self._connection.endpoint_in.read(4096, timeout=self._read_timeout)
                for frame in decoder.feed(bytes(chunk)):
                    yield frame
            except usb.core.USBTimeoutError:
                continue

    def write(self, frame: bytes, attempts: int = 3) -> None:
        with self._write_lock:
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    written = self._connection.endpoint_out.write(frame, timeout=2000)
                    if written != len(frame):
                        raise IOError(f"short USB write: {written}/{len(frame)}")
                    return
                except (usb.core.USBError, OSError) as exc:
                    last_error = exc
                    LOGGER.warning("USB write failed (attempt %d/%d)", attempt + 1, attempts)
            raise IOError("USB write failed after retries") from last_error

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()
