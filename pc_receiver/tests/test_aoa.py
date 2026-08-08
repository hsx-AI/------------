from unittest.mock import patch

from app.usb.aoa import GET_PROTOCOL, IDENTIFICATION, SEND_STRING, START_ACCESSORY, request_accessory_mode


class Device:
    idVendor = 0x1234
    idProduct = 0x5678
    calls = []

    def ctrl_transfer(self, request_type, request, value, index, data, timeout):
        self.calls.append((request_type, request, value, index, data))
        return b"\x02\x00" if request == GET_PROTOCOL else 0


def test_aoa_control_transfer_sequence():
    device = Device(); device.calls = []
    with patch("app.usb.aoa.usb.util.dispose_resources"):
        assert request_accessory_mode(device)
    assert device.calls[0][1] == GET_PROTOCOL
    assert [call[3] for call in device.calls[1:-1]] == list(range(len(IDENTIFICATION)))
    assert all(call[1] == SEND_STRING for call in device.calls[1:-1])
    assert device.calls[-1][1] == START_ACCESSORY
