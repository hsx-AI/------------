package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.rules.DuplicateGuard
import org.junit.Assert.*
import org.junit.Test

class DuplicateGuardTest { @Test fun suppressesCodeForSixtySeconds() { var now = 0L; val guard = DuplicateGuard(60_000) { now }; assertTrue(guard.acceptCode("1069", "583921")); assertFalse(guard.acceptCode("1069", "583921")); now = 60_000; assertTrue(guard.acceptCode("1069", "583921")) } }
