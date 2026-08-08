package com.example.smsusbforwarder.domain.rules

import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

class DuplicateGuard(private val ttlMillis: Long = 60_000L, private val clock: () -> Long = System::currentTimeMillis) {
    private val seen = ConcurrentHashMap<String, Long>()
    private fun key(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
    fun accept(sender: String, body: String, receivedAt: Long): Boolean {
        val now = clock(); seen.entries.removeIf { now - it.value > ttlMillis * 2 }
        return seen.putIfAbsent(key("$sender|$body|${receivedAt / ttlMillis}"), now) == null
    }
    fun acceptCode(sender: String, code: String): Boolean {
        val digest = key("code|$sender|$code"); val now = clock(); val old = seen[digest]
        return if (old == null || now - old >= ttlMillis) { seen[digest] = now; true } else false
    }
}
