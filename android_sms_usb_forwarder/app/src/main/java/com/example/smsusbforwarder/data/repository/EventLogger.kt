package com.example.smsusbforwarder.data.repository

import com.example.smsusbforwarder.data.db.EventLogDao
import com.example.smsusbforwarder.data.db.EventLogEntity
import com.example.smsusbforwarder.data.preferences.AppPreferences
import kotlinx.coroutines.flow.first

class EventLogger(private val dao: EventLogDao, private val preferences: AppPreferences) {
    suspend fun log(category: String, message: String) { if (!preferences.settings.first().retainLogs) return; dao.insert(EventLogEntity(timestamp = System.currentTimeMillis(), category = category, message = sanitize(message))); dao.trim() }
    private fun sanitize(value: String) = value.replace(Regex("(?<!\\d)\\d{4,8}(?!\\d)")) { m -> "*".repeat((m.value.length - 2).coerceAtLeast(0)) + m.value.takeLast(2) }.take(500)
}
