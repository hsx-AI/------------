package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.model.UsbConnectionState
import com.example.smsusbforwarder.usb.ConnectionPolicy
import org.junit.Assert.*
import org.junit.Test

class ConnectionPolicyTest {
    @Test fun connectedSessionIsNeverReopenedForQueueWakeup() {
        assertFalse(ConnectionPolicy.shouldOpenAttachedAccessory(UsbConnectionState.CONNECTED))
        assertFalse(ConnectionPolicy.shouldDiscover(UsbConnectionState.CONNECTED))
    }

    @Test fun disconnectedOrFailedSessionCanBeDiscovered() {
        assertTrue(ConnectionPolicy.shouldDiscover(UsbConnectionState.DISCONNECTED))
        assertTrue(ConnectionPolicy.shouldDiscover(UsbConnectionState.ERROR))
    }
}
