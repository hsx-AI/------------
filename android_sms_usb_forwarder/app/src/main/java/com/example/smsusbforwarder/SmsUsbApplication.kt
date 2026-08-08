package com.example.smsusbforwarder

import android.app.Application
import com.example.smsusbforwarder.data.db.AppDatabase
import com.example.smsusbforwarder.data.preferences.AppPreferences
import com.example.smsusbforwarder.data.repository.EventLogger
import com.example.smsusbforwarder.data.repository.MessageRepository
import com.example.smsusbforwarder.domain.security.SecretStore

class SmsUsbApplication : Application() {
    lateinit var container: AppContainer
    override fun onCreate() { super.onCreate(); val db = AppDatabase.create(this); val preferences = AppPreferences(this); val secrets = SecretStore(this); val logger = EventLogger(db.logs(), preferences); container = AppContainer(db, preferences, secrets, logger, MessageRepository(db.pending(), logger, secrets)) }
}
data class AppContainer(val database: AppDatabase, val preferences: AppPreferences, val secretStore: SecretStore, val logger: EventLogger, val messages: MessageRepository)
