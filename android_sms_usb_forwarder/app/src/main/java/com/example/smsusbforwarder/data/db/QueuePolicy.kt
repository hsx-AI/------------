package com.example.smsusbforwarder.data.db

object QueuePolicy { const val MAX_ITEMS = 100; const val TTL_MILLIS = 10 * 60_000L; fun isExpired(createdAt: Long, now: Long) = now - createdAt >= TTL_MILLIS }
