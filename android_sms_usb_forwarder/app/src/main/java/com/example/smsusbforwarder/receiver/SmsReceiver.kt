package com.example.smsusbforwarder.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import com.example.smsusbforwarder.SmsUsbApplication
import com.example.smsusbforwarder.AppState
import com.example.smsusbforwarder.domain.model.ExtractionResult
import com.example.smsusbforwarder.domain.rules.CodeExtractor
import com.example.smsusbforwarder.domain.rules.DuplicateGuard
import com.example.smsusbforwarder.service.UsbForwardService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isEmpty()) return
        val sender = messages.firstNotNullOfOrNull { it.originatingAddress } ?: "unknown"
        val body = messages.joinToString("") { it.messageBody.orEmpty() }
        val receivedAt = messages.minOf { it.timestampMillis }
        val pending = goAsync(); val app = context.applicationContext as SmsUsbApplication
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                if (!guard.accept(sender, body, receivedAt)) { app.container.logger.log("PARSE", "忽略重复短信"); return@launch }
                when (val result = CodeExtractor.extract(sender, body, app.container.preferences.settings.first().rules())) {
                    is ExtractionResult.Rejected -> app.container.logger.log("PARSE", "短信未转发：${result.reason}")
                    is ExtractionResult.Success -> if (!guard.acceptCode(sender, result.code)) app.container.logger.log("PARSE", "60 秒内重复验证码已忽略") else {
                        app.container.messages.enqueue(sender, result.code, body, receivedAt)
                            .onSuccess {
                                // An active service observes Room and wakes its sender itself. Calling
                                // startForegroundService again would run onStartCommand and used to
                                // reopen the accessory, resetting USB exactly when a message arrived.
                                if (!AppState.status.value.serviceRunning) {
                                    runCatching { UsbForwardService.start(context) }
                                        .onFailure {
                                            app.container.logger.log("ERROR", "后台限制阻止服务启动，请点通知手动启动")
                                            UsbForwardService.showStartReminder(context)
                                        }
                                }
                            }
                            .onFailure { app.container.logger.log("ERROR", it.message ?: "消息入队失败") }
                    }
                }
            } finally { pending.finish() }
        }
    }
    companion object { private val guard = DuplicateGuard() }
}
