package com.example.smsusbforwarder.usb

data class RetryPolicy(val ackTimeoutMillis: Long = 3_000, val maxRetries: Int = 3) { val maxAttempts get() = 1 + maxRetries; fun delayAfterFailedAttempt(attempt: Int): Long { require(attempt in 1..maxRetries); return attempt * 1_000L } }
