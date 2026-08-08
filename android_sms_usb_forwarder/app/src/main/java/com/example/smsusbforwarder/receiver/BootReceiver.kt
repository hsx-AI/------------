package com.example.smsusbforwarder.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import com.example.smsusbforwarder.SmsUsbApplication
import com.example.smsusbforwarder.service.UsbForwardService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch { try { val enabled = (context.applicationContext as SmsUsbApplication).container.preferences.settings.first().startOnBoot; if (enabled && Build.VERSION.SDK_INT < 35) UsbForwardService.start(context) else if (enabled) UsbForwardService.showStartReminder(context) } finally { pending.finish() } }
    }
}
