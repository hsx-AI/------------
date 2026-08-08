from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

import usb.core
import usb.util
try:
    import libusb_package
except ImportError:  # pragma: no cover - dependency error is reported by PyUSB
    libusb_package = None

LOGGER = logging.getLogger(__name__)

AOA_VENDOR_ID = 0x18D1
AOA_PRODUCT_IDS = frozenset(range(0x2D00, 0x2D06))
GET_PROTOCOL = 51
SEND_STRING = 52
START_ACCESSORY = 53
IDENTIFICATION = (
    "MyCompany",
    "SmsUsbForwarder",
    "SMS verification code USB forwarding accessory",
    "1.0",
    "https://localhost",
    "SMSUSB001",
)


@dataclass
class AoaConnection:
    device: usb.core.Device
    interface_number: int
    endpoint_in: object
    endpoint_out: object

    def close(self) -> None:
        try:
            usb.util.release_interface(self.device, self.interface_number)
        except usb.core.USBError:
            pass
        finally:
            usb.util.dispose_resources(self.device)


def is_aoa_device(device: usb.core.Device) -> bool:
    return device.idVendor == AOA_VENDOR_ID and device.idProduct in AOA_PRODUCT_IDS


def _devices() -> Iterable[usb.core.Device]:
    backend = libusb_package.get_libusb1_backend() if libusb_package is not None else None
    return usb.core.find(find_all=True, backend=backend) or ()


def request_accessory_mode(device: usb.core.Device) -> bool:
    """Probe AOA support and request re-enumeration. USB stalls are expected."""
    if is_aoa_device(device):
        return False
    try:
        raw = bytes(device.ctrl_transfer(0xC0, GET_PROTOCOL, 0, 0, 2, timeout=500))
        if len(raw) != 2:
            return False
        version = int.from_bytes(raw, "little")
        if version < 1:
            return False
        for index, value in enumerate(IDENTIFICATION):
            device.ctrl_transfer(0x40, SEND_STRING, 0, index, value.encode("utf-8") + b"\0", timeout=1000)
        device.ctrl_transfer(0x40, START_ACCESSORY, 0, 0, None, timeout=1000)
        LOGGER.info("Requested AOA mode from USB device %04x:%04x", device.idVendor, device.idProduct)
        return True
    except (usb.core.USBError, ValueError, NotImplementedError):
        return False
    finally:
        usb.util.dispose_resources(device)


def switch_first_supported_device() -> bool:
    for device in _devices():
        if request_accessory_mode(device):
            return True
    return False


def find_aoa_device() -> usb.core.Device | None:
    return next((device for device in _devices() if is_aoa_device(device)), None)


def open_aoa_device(device: usb.core.Device) -> AoaConnection:
    try:
        device.set_configuration()
    except usb.core.USBError as exc:
        # WinUSB may already have selected the sole configuration.
        LOGGER.debug("set_configuration returned %s", exc)
    configuration = device.get_active_configuration()
    for interface in configuration:
        bulk_in = None
        bulk_out = None
        for endpoint in interface:
            if usb.util.endpoint_type(endpoint.bmAttributes) != usb.util.ENDPOINT_TYPE_BULK:
                continue
            if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN:
                bulk_in = endpoint
            else:
                bulk_out = endpoint
        if bulk_in is not None and bulk_out is not None:
            number = int(interface.bInterfaceNumber)
            usb.util.claim_interface(device, number)
            return AoaConnection(device, number, bulk_in, bulk_out)
    usb.util.dispose_resources(device)
    raise RuntimeError("AOA device has no interface with bulk IN and bulk OUT endpoints")


def wait_for_aoa(timeout_seconds: float = 10.0, interval: float = 0.25) -> usb.core.Device | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        device = find_aoa_device()
        if device is not None:
            return device
        time.sleep(interval)
    return None
