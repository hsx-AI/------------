package com.example.smsusbforwarder.domain.security

class ReplayGuard(private val ttlMillis: Long, private val clock: () -> Long = System::currentTimeMillis) {
    private val seen = linkedMapOf<String, Long>()
    @Synchronized fun accept(nonce: String): Boolean { val now = clock(); seen.entries.removeIf { now - it.value > ttlMillis }; if (nonce in seen) return false; seen[nonce] = now; return true }
}
