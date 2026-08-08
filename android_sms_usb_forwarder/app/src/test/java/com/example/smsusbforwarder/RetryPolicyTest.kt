package com.example.smsusbforwarder

import com.example.smsusbforwarder.usb.RetryPolicy
import org.junit.Assert.assertEquals
import org.junit.Test

class RetryPolicyTest { @Test fun initialAttemptPlusThreeIncreasingRetries() { val p = RetryPolicy(); assertEquals(3, p.maxRetries); assertEquals(4, p.maxAttempts); assertEquals(listOf(1000L, 2000L, 3000L), (1..3).map(p::delayAfterFailedAttempt)) } }
