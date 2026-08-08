package com.example.smsusbforwarder.usb

import com.example.smsusbforwarder.domain.model.UsbConnectionState

object ConnectionPolicy {
    fun shouldOpenAttachedAccessory(state: UsbConnectionState): Boolean =
        state != UsbConnectionState.CONNECTED && state != UsbConnectionState.CONNECTING

    fun shouldDiscover(state: UsbConnectionState): Boolean =
        state == UsbConnectionState.DISCONNECTED || state == UsbConnectionState.ERROR
}
