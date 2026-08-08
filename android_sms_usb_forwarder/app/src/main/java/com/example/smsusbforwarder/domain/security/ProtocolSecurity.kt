package com.example.smsusbforwarder.domain.security

import com.example.smsusbforwarder.domain.model.SmsCodeMessage
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object ProtocolSecurity {
    val json = Json { encodeDefaults = true; explicitNulls = false; ignoreUnknownKeys = false }
    fun canonicalize(element: JsonElement): String = when (element) {
        is JsonObject -> element.entries.sortedBy { it.key }.joinToString(",", "{", "}") { json.encodeToString(it.key) + ":" + canonicalize(it.value) }
        is JsonArray -> element.joinToString(",", "[", "]") { canonicalize(it) }
        else -> element.toString()
    }
    fun signingBytes(message: SmsCodeMessage): ByteArray = canonicalize(JsonObject(json.parseToJsonElement(json.encodeToString(message)).jsonObject.filterKeys { it != "hmac" })).toByteArray(Charsets.UTF_8)
    fun sign(message: SmsCodeMessage, secret: ByteArray): SmsCodeMessage {
        require(secret.isNotEmpty()); val mac = Mac.getInstance("HmacSHA256"); mac.init(SecretKeySpec(secret, "HmacSHA256"))
        return message.copy(hmac = mac.doFinal(signingBytes(message)).joinToString("") { "%02x".format(it) })
    }
    fun verify(message: SmsCodeMessage, secret: ByteArray) = MessageDigest.isEqual(sign(message.copy(hmac = ""), secret).hmac.toByteArray(), message.hmac.toByteArray())
}
