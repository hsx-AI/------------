package com.example.smsusbforwarder.data.repository

import android.util.Base64
import com.example.smsusbforwarder.AppState
import com.example.smsusbforwarder.data.db.PendingMessageDao
import com.example.smsusbforwarder.data.db.PendingMessageEntity
import com.example.smsusbforwarder.domain.model.SmsCodeMessage
import com.example.smsusbforwarder.domain.security.ProtocolSecurity
import com.example.smsusbforwarder.domain.security.SecretStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.onEach
import kotlinx.serialization.encodeToString
import java.security.SecureRandom
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.util.UUID

class MessageRepository(private val dao: PendingMessageDao, private val logger: EventLogger, private val secrets: SecretStore) {
    fun count(now: Long = System.currentTimeMillis()): Flow<Int> = dao.count(now).onEach { AppState.status.value = AppState.status.value.copy(pendingCount = it) }
    suspend fun enqueue(sender: String, code: String, smsText: String, receivedAtMillis: Long): Result<String> = runCatching {
        val secret = secrets.get() ?: error("请先设置 HMAC 共享密钥")
        val nonce = ByteArray(18).also(SecureRandom()::nextBytes).let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING) }
        val now = System.currentTimeMillis(); val id = UUID.randomUUID().toString()
        val base = SmsCodeMessage(messageId = id, sender = sender.take(64), code = code, smsTextMasked = maskText(smsText, code), receivedAt = iso(receivedAtMillis), sentAt = iso(now), nonce = nonce)
        val payload = ProtocolSecurity.json.encodeToString(ProtocolSecurity.sign(base, secret))
        dao.deleteExpired(now)
        val excess = dao.totalCount() - 99
        if (excess > 0) dao.deleteOldest(excess)
        check(dao.insert(PendingMessageEntity(id, payload, now, now + 10 * 60_000L)) != -1L)
        logger.log("PARSE", "验证码已提取并加入待发送队列，末两位 ${code.takeLast(2)}")
        AppState.status.value = AppState.status.value.copy(lastSmsAt = receivedAtMillis, lastMaskedCode = "**${code.takeLast(2)}")
        id
    }
    suspend fun ready() = dao.ready(System.currentTimeMillis())
    suspend fun ack(id: String) { dao.delete(id); AppState.status.value = AppState.status.value.copy(lastForwardedAt = System.currentTimeMillis()); logger.log("ACK", "消息 $id 已送达") }
    suspend fun attempts(id: String, count: Int) = dao.updateAttempts(id, count)
    suspend fun clear() = dao.clear()
    suspend fun cleanup() = dao.deleteExpired(System.currentTimeMillis())
    private fun iso(millis: Long) = OffsetDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneId.systemDefault()).toString()
    private fun maskText(text: String, code: String) = text.replace(code, code.take(2) + "*".repeat((code.length - 2).coerceAtLeast(0))).take(256)
}
