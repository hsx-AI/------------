package com.example.smsusbforwarder.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.example.smsusbforwarder.*
import com.example.smsusbforwarder.domain.model.*
import com.example.smsusbforwarder.usb.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.serialization.decodeFromString
import java.util.concurrent.ConcurrentHashMap

class UsbForwardService : Service(), UsbAccessoryManager.Listener {
    private val job = SupervisorJob(); private val scope = CoroutineScope(job + Dispatchers.Default)
    private lateinit var usb: UsbAccessoryManager; private lateinit var app: SmsUsbApplication
    private val wake = Channel<Unit>(Channel.CONFLATED); private val awaiting = ConcurrentHashMap<String, CompletableDeferred<Unit>>()

    override fun onCreate() {
        super.onCreate(); app = application as SmsUsbApplication; createChannel(); startForegroundCompat(notification("正在启动")); AppState.status.value = AppState.status.value.copy(serviceRunning = true)
        usb = UsbAccessoryManager(this, scope, this); usb.start()
        scope.launch { app.container.messages.count().collectLatest { updateNotification(); wake.trySend(Unit) } }
        scope.launch { senderLoop() }
        scope.launch { while (isActive) { delay(60_000); app.container.messages.cleanup(); wake.trySend(Unit) } }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val accessory = intent?.let { accessory(it) }
        when {
            accessory != null && ConnectionPolicy.shouldOpenAttachedAccessory(usb.state.value) -> usb.start(accessory)
            accessory == null && ConnectionPolicy.shouldDiscover(usb.state.value) -> usb.discover()
        }
        wake.trySend(Unit)
        return START_STICKY
    }
    private suspend fun senderLoop() { for (signal in wake) { if (usb.state.value != UsbConnectionState.CONNECTED) continue; app.container.messages.ready().forEach { pending -> if (usb.state.value == UsbConnectionState.CONNECTED) sendWithAck(pending.messageId, pending.payloadJson, pending.attemptCount) } } }
    private suspend fun sendWithAck(id: String, json: String, previous: Int) {
        for (attempt in 1..4) {
            val deferred = CompletableDeferred<Unit>(); awaiting[id] = deferred
            try { usb.write(FrameCodec.encode(json)); app.container.messages.attempts(id, previous + attempt); withTimeout(3_000L) { deferred.await() }; app.container.messages.ack(id); return }
            catch (_: TimeoutCancellationException) { app.container.logger.log("SEND", "ACK 超时，第 $attempt 次") }
            catch (e: Exception) { app.container.logger.log("ERROR", e.message ?: "USB 写入失败"); return }
            finally { awaiting.remove(id, deferred) }
            if (attempt < 4) delay(attempt * 1_000L)
        }
        app.container.logger.log("SEND", "重试耗尽，消息保留在队列")
    }
    override suspend fun onJson(json: String) {
        runCatching { com.example.smsusbforwarder.domain.security.ProtocolSecurity.json.decodeFromString<AckMessage>(json) }.onSuccess { ack ->
            if (ack.protocolVersion == 1 && ack.type == "ack" && ack.status == "accepted") awaiting[ack.messageId]?.complete(Unit) else app.container.logger.log("ERROR", "收到无效 ACK")
        }.onFailure { app.container.logger.log("ERROR", "ACK JSON 解析失败") }
    }
    override fun onState(state: UsbConnectionState, detail: String) { AppState.status.value = AppState.status.value.copy(usbState = state, detail = detail); updateNotification(); if (state == UsbConnectionState.CONNECTED) { scope.launch { app.container.logger.log("USB", "Accessory 已连接") }; wake.trySend(Unit) } }
    private fun createChannel() { (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(NotificationChannel(CHANNEL, "USB 转发服务", NotificationManager.IMPORTANCE_LOW)) }
    private fun notification(text: String): Notification { val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT); return NotificationCompat.Builder(this, CHANNEL).setSmallIcon(com.example.smsusbforwarder.R.drawable.ic_launcher).setContentTitle("短信 USB 转发服务").setContentText(text).setOngoing(true).setContentIntent(open).setOnlyAlertOnce(true).build() }
    private fun updateNotification() { NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, notification("USB：${AppState.status.value.usbState.name} · 待发送 ${AppState.status.value.pendingCount}")) }
    private fun startForegroundCompat(n: Notification) { if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE) else startForeground(NOTIFICATION_ID, n) }
    override fun onDestroy() { usb.close(); job.cancel(); AppState.status.value = AppState.status.value.copy(serviceRunning = false, usbState = UsbConnectionState.DISCONNECTED); super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null
    @Suppress("DEPRECATION") private fun accessory(intent: Intent): UsbAccessory? = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY, UsbAccessory::class.java) else intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY)
    companion object {
        private const val CHANNEL = "usb_forward"; private const val NOTIFICATION_ID = 1001; private const val REMINDER_ID = 1002
        fun start(context: Context, accessory: UsbAccessory? = null) { val intent = Intent(context, UsbForwardService::class.java); if (accessory != null) intent.putExtra(UsbManager.EXTRA_ACCESSORY, accessory); ContextCompat.startForegroundService(context, intent) }
        fun stop(context: Context) = context.stopService(Intent(context, UsbForwardService::class.java))
        fun showStartReminder(context: Context) { val manager = context.getSystemService(NotificationManager::class.java); manager.createNotificationChannel(NotificationChannel(CHANNEL, "USB 转发服务", NotificationManager.IMPORTANCE_LOW)); val pi = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT); manager.notify(REMINDER_ID, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(com.example.smsusbforwarder.R.drawable.ic_launcher).setContentTitle("短信 USB 转发服务未启动").setContentText("系统限制开机后台启动，请点此打开并启动服务").setContentIntent(pi).setAutoCancel(true).build()) }
    }
}
