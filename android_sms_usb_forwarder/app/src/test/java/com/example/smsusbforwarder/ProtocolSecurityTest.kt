package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.model.SmsCodeMessage
import com.example.smsusbforwarder.domain.security.ProtocolSecurity
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ProtocolSecurityTest {
    @Test fun canonicalJsonSortsKeysWithoutAsciiEscaping() { assertEquals("{\"a\":\"中文\",\"b\":2}", ProtocolSecurity.canonicalize(Json.parseToJsonElement("{\"b\":2,\"a\":\"中文\"}"))) }
    @Test fun hmacRoundTripAndTamperDetection() { val base = SmsCodeMessage(messageId="550e8400-e29b-41d4-a716-446655440000", sender="1069", code="583921", smsTextMasked="验证码 58****", receivedAt="2026-08-01T11:00:00+08:00", sentAt="2026-08-01T11:00:01+08:00", nonce="abc"); val signed = ProtocolSecurity.sign(base, "secret".toByteArray()); assertTrue(ProtocolSecurity.verify(signed, "secret".toByteArray())); assertFalse(ProtocolSecurity.verify(signed.copy(code="000000"), "secret".toByteArray())) }
    @Test fun matchesPythonGoldenVector() { val base = SmsCodeMessage(messageId="550e8400-e29b-41d4-a716-446655440000", sender="10690000", code="583921", smsTextMasked="您的验证码为 58****", receivedAt="2026-08-01T11:00:00+08:00", sentAt="2026-08-01T11:00:01+08:00", nonce="abcdefghijklmnop"); assertEquals("12222e9ed1e68b7a1205435df12e8a34ec8f4d8ddb1cf2d7c25b23c18f883824", ProtocolSecurity.sign(base, "shared-secret-测试".toByteArray()).hmac) }
}
