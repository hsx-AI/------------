package com.example.smsusbforwarder

import com.example.smsusbforwarder.data.db.QueuePolicy
import org.junit.Assert.*
import org.junit.Test

class QueuePolicyTest { @Test fun expiresAtTenMinutes() { assertFalse(QueuePolicy.isExpired(0, 599_999)); assertTrue(QueuePolicy.isExpired(0, 600_000)); assertEquals(100, QueuePolicy.MAX_ITEMS) } }
