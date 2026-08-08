# Android SMS USB Forwarder

完整 Android 客户端，包名 `com.example.smsusbforwarder`，`minSdk 26`、`targetSdk 36`。采用 Kotlin、Gradle Kotlin DSL、Jetpack Compose、MVVM 状态管理、Room、DataStore、协程和 Android Open Accessory API。

## 环境与构建

建议使用支持 AGP 8.13 的稳定版 Android Studio、JDK 17 和 Android SDK Platform 36。Android Studio 打开本目录后等待 Gradle Sync，然后执行：

```powershell
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

如果 Windows 下工程父目录包含中文，AGP 可能可以编译 App，却在启动 JVM 单元测试时出现测试类 `ClassNotFoundException`。可临时映射一个纯 ASCII 盘符后构建，文件仍保存在原目录：

```powershell
subst S: "E:\Desktop\tuixiu_protect\汽发工艺核电平台数据获取\android_sms_usb_forwarder"
S:
.\gradlew.bat clean testDebugUnitTest assembleDebug
E:
subst S: /D
```

APK 位于 `app\build\outputs\apk\debug\app-debug.apk`。安装：

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

项目不申请 `READ_SMS`，只在收到 `SMS_RECEIVED` 广播时从 Intent PDU 读取新短信。首次打开请授予短信和通知权限。部分厂商系统还需要在系统设置中允许自启动并取消对本 App 的过度省电限制。

### 一加 / OPPO / ColorOS 后台设置

系统菜单名称会随 ColorOS 版本略有不同，请为 `SMS USB Forwarder` 完成以下设置：

- 电池用量或应用耗电管理：选择“允许后台活动”或“不限制”；
- 自启动管理：允许应用自启动；
- 最近任务界面：锁定本应用，避免一键清理；
- 保留前台服务的长期通知，不要在通知中停止服务；
- 启动服务后再退到后台，主页应持续显示“前台服务：运行中”。

如果系统已杀死前台服务，普通应用在 Android 新版本上不一定能从后台短信广播重新启动 connected-device 前台服务。此时短信仍会先安全入 Room 队列，并显示手动启动提醒；重新打开 App、点击“启动服务”且 USB 恢复后会自动补发未过期消息。

版本 1.0.1 修复了消息到达时重复执行 `openAccessory()` 导致 USB 复位的问题：已连接的会话只唤醒 Room 发送队列，不再重开 USB。

## 首次配置

1. 打开“设置”，填写允许的发送方、必含关键词、正则和验证码长度。
2. 输入足够长的 HMAC 共享密钥并保存。输入内容不会 trim；电脑端必须配置逐字节相同的 UTF-8 密钥。
3. 密钥由 Android Keystore 中的 AES-GCM 密钥加密后保存，不以明文写入数据库、偏好文件或代码。
4. 回到主页，授予权限并点“启动服务”。长期可见通知只显示连接和队列状态。
5. 连接电脑后，由电脑发起 AOA 握手。手机重新枚举时接受 USB accessory 授权，并可勾选默认用于该 accessory。

## 模拟测试

点击主页“测试发送”。App 会把以下模拟短信送入与真实短信完全相同的规则、签名和 USB 队列流程：

```text
【内部系统】您的登录验证码为 583921，5 分钟内有效。
```

若提示规则未通过，请检查发送方 `10690000`、关键词和验证码长度。没有配置共享密钥时消息不会入队。

## 数据和可靠性

- 一次广播中的多个 PDU 按系统返回顺序拼接，发送方取第一条有效地址，接收时间取最早分段时间。
- 同一短信指纹避免重复广播处理；同一发送方和验证码 60 秒内只发送一次。
- 不能唯一确定候选验证码时拒绝转发。
- Room 只保存已脱敏并签名的协议消息，不保存完整短信；最多 100 条，10 分钟过期。
- ACK 等待 3 秒，使用同一 `messageId` 最多尝试 3 次，间隔递增；断线后保留并在 USB 恢复时重发。
- 日志最多 200 条，数字验证码自动脱敏；可关闭持久日志或从日志页导出脱敏诊断文本。

## AOA 行为

Manifest 通过 `res/xml/accessory_filter.xml` 匹配：

- manufacturer: `MyCompany`
- model: `SmsUsbForwarder`
- version: `1.0`

description、URI、serial 由 Windows Host 在 AOA `SEND_STRING` 阶段发送，不是 Android accessory filter 的匹配属性。App 同时处理冷启动 attach Intent、`onNewIntent`、动态 attach/detach 和 permission 回调。所有 `openAccessory` 流 I/O 都在 `Dispatchers.IO`，断线及取消时在 `finally` 关闭流和文件描述符。

普通 USB/MTP 连接不会立刻生成 `UsbAccessory`。必须先运行电脑端，成功发送 `START_ACCESSORY` 并等待手机重新枚举。不要把 Android 的 ADB/MTP 组合接口驱动整体替换为 WinUSB。

## 开机启动说明

Android 新版本严格限制开机广播直接启动某些前台服务。本工程在旧版本且用户启用开机启动时尝试启动；Android 15 及以上改为显示提醒通知，由用户点击进入 App 启动服务。这样不会用轮询或频繁唤醒规避系统限制。

## 关键源文件

- `receiver/SmsReceiver.kt`：PDU 合并和规则入口。
- `domain/rules/CodeExtractor.kt`：候选评分与歧义拒绝。
- `domain/security/ProtocolSecurity.kt`：规范 JSON 和 HMAC。
- `domain/security/SecretStore.kt`：Keystore AES-GCM 包装。
- `usb/UsbAccessoryManager.kt`：授权、attach/detach、文件描述符与读写。
- `service/UsbForwardService.kt`：前台生命周期、ACK 与队列调度。
- `data/db/AppDatabase.kt`：Room 队列与脱敏事件日志。
- `MainActivity.kt`：Compose UI 和 ViewModel。

## 已包含单元测试

验证码提取、多数字歧义、HMAC、规范 JSON、帧拆包/粘包、短信/验证码去重、nonce 防重放、ACK 重试策略和队列过期策略均位于 `app/src/test`。

真机验证 SMS 广播、Keystore、Room 与 USB accessory 生命周期仍需 Android 设备；普通 JVM 测试不能模拟真实 USB 重新枚举。
