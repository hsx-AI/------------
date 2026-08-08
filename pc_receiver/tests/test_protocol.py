import struct

import pytest

from app.usb.protocol import FrameDecoder, ProtocolError, encode_frame


def test_fragmentation_and_coalescing():
    data = encode_frame('{"a":1}') + encode_frame('{"b":2}')
    decoder = FrameDecoder()
    assert decoder.feed(data[:3]) == []
    assert decoder.feed(data[3:8]) == []
    assert decoder.feed(data[8:]) == ['{"a":1}', '{"b":2}']


def test_rejects_oversize_length_immediately():
    with pytest.raises(ProtocolError):
        FrameDecoder().feed(struct.pack(">I", 8193))


def test_rejects_invalid_utf8():
    with pytest.raises(ProtocolError):
        FrameDecoder().feed(struct.pack(">I", 1) + b"\xff")
