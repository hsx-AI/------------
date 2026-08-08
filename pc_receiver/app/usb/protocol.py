from __future__ import annotations

import json
import struct
from typing import Any

MAX_PAYLOAD = 8192


class ProtocolError(ValueError):
    pass


def encode_frame(payload: dict[str, Any] | str) -> bytes:
    text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    body = text.encode("utf-8")
    if not 1 <= len(body) <= MAX_PAYLOAD:
        raise ProtocolError(f"invalid payload length: {len(body)}")
    return struct.pack(">I", len(body)) + body


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        self._buffer.extend(chunk)
        frames: list[str] = []
        while len(self._buffer) >= 4:
            length = struct.unpack_from(">I", self._buffer)[0]
            if not 1 <= length <= MAX_PAYLOAD:
                raise ProtocolError(f"invalid frame length: {length}")
            if len(self._buffer) < 4 + length:
                break
            raw = bytes(self._buffer[4 : 4 + length])
            del self._buffer[: 4 + length]
            try:
                frames.append(raw.decode("utf-8", errors="strict"))
            except UnicodeDecodeError as exc:
                raise ProtocolError("payload is not strict UTF-8") from exc
        return frames
