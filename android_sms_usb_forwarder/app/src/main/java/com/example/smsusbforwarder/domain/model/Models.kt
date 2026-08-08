package com.example.smsusbforwarder.domain.model

import kotlinx.serialization.Serializable

@Serializable
data class SmsCodeMessage(val protocolVersion: Int = 1, val messageId: String, val type: String = "sms_code", val sender: String, val code: String, val smsTextMasked: String, val receivedAt: String, val sentAt: String, val nonce: String, val hmac: String = "")

@Serializable
data class AckMessage(val protocolVersion: Int, val type: String, val messageId: String, val status: String, val receivedAt: String)

data class SmsEnvelope(val sender: String, val body: String, val receivedAtMillis: Long)
data class ExtractRules(val allowedSenders: List<String> = emptyList(), val requiredKeywords: List<String> = emptyList(), val regex: String = DEFAULT_CODE_REGEX, val codeLength: Int = 6, val allowAlphanumeric: Boolean = false) {
    companion object { const val DEFAULT_CODE_REGEX = "(?<!\\d)\\d{4,8}(?!\\d)" }
}
sealed interface ExtractionResult { data class Success(val code: String) : ExtractionResult; data class Rejected(val reason: String) : ExtractionResult }
enum class UsbConnectionState { DISCONNECTED, PERMISSION_REQUIRED, CONNECTING, CONNECTED, ERROR }
data class AppStatus(val usbState: UsbConnectionState = UsbConnectionState.DISCONNECTED, val serviceRunning: Boolean = false, val lastSmsAt: Long? = null, val lastForwardedAt: Long? = null, val pendingCount: Int = 0, val lastMaskedCode: String? = null, val detail: String = "")
