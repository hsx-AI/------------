package com.example.smsusbforwarder.usb

import android.app.PendingIntent
import android.content.*
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import androidx.core.content.ContextCompat
import com.example.smsusbforwarder.domain.model.UsbConnectionState
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException

class UsbAccessoryManager(private val context: Context, private val scope: CoroutineScope, private val listener: Listener) : AutoCloseable {
    interface Listener { suspend fun onJson(json: String); fun onState(state: UsbConnectionState, detail: String = "") }
    private val manager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private var sessionJob: Job? = null
    private var registered = false
    private val permissionAction = "${context.packageName}.USB_PERMISSION"
    val state = MutableStateFlow(UsbConnectionState.DISCONNECTED)

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            when (intent.action) {
                permissionAction -> accessory(intent)?.let { if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) open(it) else update(UsbConnectionState.PERMISSION_REQUIRED, "USB 权限被拒绝") }
                UsbManager.ACTION_USB_ACCESSORY_ATTACHED -> accessory(intent)?.let(::connect)
                UsbManager.ACTION_USB_ACCESSORY_DETACHED -> { closeSession(); discover() }
            }
        }
    }

    fun start(initialAccessory: UsbAccessory? = null) {
        if (!registered) {
            val filter = IntentFilter().apply { addAction(permissionAction); addAction(UsbManager.ACTION_USB_ACCESSORY_ATTACHED); addAction(UsbManager.ACTION_USB_ACCESSORY_DETACHED) }
            ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_EXPORTED); registered = true
        }
        if (initialAccessory != null) connect(initialAccessory) else discover()
    }
    fun discover() { manager.accessoryList?.firstOrNull(::matches)?.let(::connect) ?: update(UsbConnectionState.DISCONNECTED, "等待电脑切换 AOA 模式") }
    private fun connect(accessory: UsbAccessory) {
        if (!matches(accessory)) return
        if (!manager.hasPermission(accessory)) {
            update(UsbConnectionState.PERMISSION_REQUIRED, "等待 USB 授权")
            val pi = PendingIntent.getBroadcast(context, 0, Intent(permissionAction).setPackage(context.packageName), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            manager.requestPermission(accessory, pi)
        } else open(accessory)
    }
    private fun open(accessory: UsbAccessory) {
        closeSession(); update(UsbConnectionState.CONNECTING)
        val descriptor = manager.openAccessory(accessory) ?: return update(UsbConnectionState.ERROR, "openAccessory 返回空")
        sessionJob = scope.launch(Dispatchers.IO) {
            val input = FileInputStream(descriptor.fileDescriptor); val output = FileOutputStream(descriptor.fileDescriptor)
            activeOutput = output
            try {
                update(UsbConnectionState.CONNECTED, "${accessory.manufacturer} / ${accessory.model}")
                val decoder = FrameDecoder(); val chunk = ByteArray(4096)
                while (isActive) { val count = input.read(chunk); if (count < 0) throw IOException("USB EOF"); decoder.feed(chunk, count).forEach { listener.onJson(it) } }
            } catch (e: CancellationException) { throw e } catch (e: Exception) { update(UsbConnectionState.ERROR, e.message ?: "USB 读取失败") }
            finally { activeOutput = null; runCatching { input.close() }; runCatching { output.close() }; runCatching { descriptor.close() }; update(UsbConnectionState.DISCONNECTED, "USB 已断开") }
        }
    }
    @Volatile private var activeOutput: FileOutputStream? = null
    suspend fun write(frame: ByteArray) = withContext(Dispatchers.IO) { val output = activeOutput ?: throw IOException("USB 未连接"); output.write(frame); output.flush() }
    private fun matches(a: UsbAccessory) = a.manufacturer == "MyCompany" && a.model == "SmsUsbForwarder"
    @Suppress("DEPRECATION") private fun accessory(intent: Intent): UsbAccessory? = if (android.os.Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY, UsbAccessory::class.java) else intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY)
    private fun update(value: UsbConnectionState, detail: String = "") { state.value = value; listener.onState(value, detail) }
    private fun closeSession() { sessionJob?.cancel(); sessionJob = null; activeOutput = null }
    override fun close() { closeSession(); if (registered) { runCatching { context.unregisterReceiver(receiver) }; registered = false } }
}
