package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.model.AppStatus
import kotlinx.coroutines.flow.MutableStateFlow

object AppState { val status = MutableStateFlow(AppStatus()) }
