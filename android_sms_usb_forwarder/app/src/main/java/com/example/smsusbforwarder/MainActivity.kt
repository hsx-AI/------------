package com.example.smsusbforwarder

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.example.smsusbforwarder.data.preferences.UserSettings
import com.example.smsusbforwarder.domain.model.ExtractionResult
import com.example.smsusbforwarder.domain.rules.CodeExtractor
import com.example.smsusbforwarder.service.UsbForwardService
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { vm.refreshPermission() }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); handleAccessory(intent); setContent { MaterialTheme { AppUi(vm, ::requestPermissions) } } }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleAccessory(intent) }
    private fun requestPermissions() { val wanted = mutableListOf(Manifest.permission.RECEIVE_SMS); if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS; permissions.launch(wanted.toTypedArray()) }
    private fun handleAccessory(intent: Intent?) { if (intent?.action == UsbManager.ACTION_USB_ACCESSORY_ATTACHED) accessory(intent)?.let { UsbForwardService.start(this, it) } }
    @Suppress("DEPRECATION") private fun accessory(intent: Intent): UsbAccessory? = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY, UsbAccessory::class.java) else intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY)
}

class MainViewModel(app: android.app.Application) : AndroidViewModel(app) {
    private val container = (app as SmsUsbApplication).container
    val status = AppState.status.asStateFlow()
    val settings = container.preferences.settings.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), UserSettings())
    val logs = container.database.logs().observe().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
    private val _smsPermission = MutableStateFlow(false); val smsPermission = _smsPermission.asStateFlow()
    private val _message = MutableStateFlow<String?>(null); val message = _message.asStateFlow()
    init { refreshPermission(); viewModelScope.launch { container.messages.count().collect() } }
    fun refreshPermission() { _smsPermission.value = ContextCompat.checkSelfPermission(getApplication(), Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED }
    fun start() = UsbForwardService.start(getApplication())
    fun stop() = UsbForwardService.stop(getApplication())
    fun save(settings: UserSettings, secret: String) = viewModelScope.launch { runCatching { container.preferences.save(settings); if (secret.isNotEmpty()) container.secretStore.set(secret) }.onSuccess { _message.value = "设置已保存" }.onFailure { _message.value = it.message } }
    fun clearQueue() = viewModelScope.launch { container.messages.clear(); _message.value = "待发送队列已清空" }
    fun testSend() = viewModelScope.launch {
        val text = "【内部系统】您的登录验证码为 583921，5 分钟内有效。"; val result = CodeExtractor.extract("10690000", text, settings.value.rules())
        if (result is ExtractionResult.Success) container.messages.enqueue("10690000", result.code, text, System.currentTimeMillis()).onSuccess { start(); _message.value = "模拟消息已加入队列" }.onFailure { _message.value = it.message }
        else _message.value = "模拟消息未通过当前规则：${(result as ExtractionResult.Rejected).reason}"
    }
    fun consumeMessage() { _message.value = null }
    fun secretConfigured() = container.secretStore.isConfigured()
}

private enum class Page { HOME, SETTINGS, LOGS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun AppUi(vm: MainViewModel, requestPermissions: () -> Unit) {
    var page by remember { mutableStateOf(Page.HOME) }; val notice by vm.message.collectAsStateWithLifecycle()
    Scaffold(topBar = { TopAppBar(title = { Text("SMS USB Forwarder") }) }, bottomBar = { NavigationBar { Page.entries.forEach { item -> NavigationBarItem(selected = page == item, onClick = { page = item }, icon = { Text(when(item) { Page.HOME -> "●"; Page.SETTINGS -> "⚙"; Page.LOGS -> "≡" }) }, label = { Text(when(item) { Page.HOME -> "主页"; Page.SETTINGS -> "设置"; Page.LOGS -> "日志" }) }) } } }, snackbarHost = { SnackbarHost(remember { SnackbarHostState() }) }) { padding ->
        Box(Modifier.padding(padding)) { when (page) { Page.HOME -> HomePage(vm, requestPermissions); Page.SETTINGS -> SettingsPage(vm); Page.LOGS -> LogsPage(vm) } }
        notice?.let { AlertDialog(onDismissRequest = vm::consumeMessage, confirmButton = { TextButton(onClick = vm::consumeMessage) { Text("确定") } }, text = { Text(it) }) }
    }
}

@Composable private fun HomePage(vm: MainViewModel, requestPermissions: () -> Unit) {
    val status by vm.status.collectAsStateWithLifecycle(); val granted by vm.smsPermission.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        StatusRow("短信权限", if (granted) "已授权" else "未授权"); StatusRow("USB accessory", status.usbState.name); StatusRow("前台服务", if (status.serviceRunning) "运行中" else "已停止")
        StatusRow("最近短信", formatTime(status.lastSmsAt)); StatusRow("最近成功转发", formatTime(status.lastForwardedAt)); StatusRow("待发送数量", status.pendingCount.toString()); StatusRow("最近验证码", status.lastMaskedCode ?: "—")
        if (status.detail.isNotBlank()) Text(status.detail, style = MaterialTheme.typography.bodySmall)
        if (!granted) Button(onClick = requestPermissions, Modifier.fillMaxWidth()) { Text("授予短信权限") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Button(onClick = vm::start, modifier = Modifier.weight(1f)) { Text("启动服务") }; OutlinedButton(onClick = vm::stop, modifier = Modifier.weight(1f)) { Text("停止服务") } }
        Button(onClick = vm::testSend, modifier = Modifier.fillMaxWidth()) { Text("测试发送") }
    }
}
@Composable private fun StatusRow(label: String, value: String) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label); Text(value) } }
private fun formatTime(value: Long?) = value?.let { java.text.DateFormat.getDateTimeInstance().format(java.util.Date(it)) } ?: "—"

@Composable private fun SettingsPage(vm: MainViewModel) {
    val current by vm.settings.collectAsStateWithLifecycle(); var draft by remember(current) { mutableStateOf(current) }; var secret by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { OutlinedTextField(draft.allowedSenders, { draft = draft.copy(allowedSenders = it) }, label = { Text("允许发送方（每行一个，空表示不限）") }, modifier = Modifier.fillMaxWidth()) }
        item { OutlinedTextField(draft.requiredKeywords, { draft = draft.copy(requiredKeywords = it) }, label = { Text("必含关键词（逗号分隔）") }, modifier = Modifier.fillMaxWidth()) }
        item { OutlinedTextField(draft.regex, { draft = draft.copy(regex = it) }, label = { Text("验证码正则") }, modifier = Modifier.fillMaxWidth()) }
        item { OutlinedTextField(draft.codeLength.toString(), { it.toIntOrNull()?.takeIf { n -> n in 4..32 }?.let { n -> draft = draft.copy(codeLength = n) } }, label = { Text("验证码长度") }, modifier = Modifier.fillMaxWidth()) }
        item { SettingSwitch("允许字母数字混合", draft.allowAlphanumeric) { draft = draft.copy(allowAlphanumeric = it) }; SettingSwitch("开机启动", draft.startOnBoot) { draft = draft.copy(startOnBoot = it) }; SettingSwitch("保存脱敏日志", draft.retainLogs) { draft = draft.copy(retainLogs = it) } }
        item { OutlinedTextField(secret, { secret = it }, label = { Text(if (vm.secretConfigured()) "共享密钥（已配置；留空不修改）" else "共享密钥（尚未配置）") }, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth()) }
        item { Button(onClick = { vm.save(draft, secret); secret = "" }, Modifier.fillMaxWidth()) { Text("保存设置") }; OutlinedButton(onClick = vm::clearQueue, Modifier.fillMaxWidth()) { Text("清空待发送队列") } }
    }
}
@Composable private fun SettingSwitch(text: String, checked: Boolean, change: (Boolean) -> Unit) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(text); Switch(checked, change) } }

@Composable private fun LogsPage(vm: MainViewModel) { val logs by vm.logs.collectAsStateWithLifecycle(); val context = LocalContext.current; LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { item { Text("仅保存最近 200 条脱敏事件", style = MaterialTheme.typography.bodySmall); OutlinedButton(onClick = { val text = logs.reversed().joinToString("\n") { "${formatTime(it.timestamp)} [${it.category}] ${it.message}" }; context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), "导出诊断日志")) }) { Text("导出脱敏诊断日志") } }; items(logs, key = { it.id }) { log -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(10.dp)) { Text("${log.category} · ${formatTime(log.timestamp)}", style = MaterialTheme.typography.labelMedium); Text(log.message) } } } } }
