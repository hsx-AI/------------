package com.example.smsusbforwarder.data.preferences

import android.content.Context
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import com.example.smsusbforwarder.domain.model.ExtractRules
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore("settings")
data class UserSettings(val allowedSenders: String = "", val requiredKeywords: String = "验证码", val regex: String = ExtractRules.DEFAULT_CODE_REGEX, val codeLength: Int = 6, val allowAlphanumeric: Boolean = false, val startOnBoot: Boolean = false, val retainLogs: Boolean = true) {
    fun rules() = ExtractRules(allowedSenders.lines(), requiredKeywords.split(',').map(String::trim), regex, codeLength, allowAlphanumeric).let { it.copy(allowedSenders = it.allowedSenders.filter(String::isNotBlank), requiredKeywords = it.requiredKeywords.filter(String::isNotBlank)) }
}

class AppPreferences(private val context: Context) {
    private object K { val senders = stringPreferencesKey("senders"); val keywords = stringPreferencesKey("keywords"); val regex = stringPreferencesKey("regex"); val length = intPreferencesKey("length"); val alpha = booleanPreferencesKey("alpha"); val boot = booleanPreferencesKey("boot"); val logs = booleanPreferencesKey("logs") }
    val settings: Flow<UserSettings> = context.dataStore.data.map { p -> UserSettings(p[K.senders] ?: "", p[K.keywords] ?: "验证码", p[K.regex] ?: ExtractRules.DEFAULT_CODE_REGEX, p[K.length] ?: 6, p[K.alpha] ?: false, p[K.boot] ?: false, p[K.logs] ?: true) }
    suspend fun save(value: UserSettings) = context.dataStore.edit { p -> p[K.senders] = value.allowedSenders; p[K.keywords] = value.requiredKeywords; p[K.regex] = value.regex; p[K.length] = value.codeLength; p[K.alpha] = value.allowAlphanumeric; p[K.boot] = value.startOnBoot; p[K.logs] = value.retainLogs }
}
