package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.security.ReplayGuard
import org.junit.Assert.*
import org.junit.Test

class ReplayGuardTest { @Test fun nonceCannotReplayUntilExpiry() { var now = 1L; val guard = ReplayGuard(100) { now }; assertTrue(guard.accept("n")); assertFalse(guard.accept("n")); now = 102; assertTrue(guard.accept("n")) } }
