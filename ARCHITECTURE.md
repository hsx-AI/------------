# 短信验证码 USB 转发系统：第一阶段设计

## 1. 范围与安全边界

本系统仅用于操作者有合法访问权限的内部系统。Android 手机从 `SMS_RECEIVED` 广播携带的 PDU 中读取新短信，不扫描短信数据库、不要求 Root，也不使用 Wi-Fi、蓝牙、局域网或云服务。电脑是 USB Host，手机是 AOA accessory/device；Windows 端通过 libusb/WinUSB 通信，不创建 COM 端口。

默认不传输完整短信；界面、通知和日志均不显示完整验证码。共享密钥由用户分别配置，Android 端用 Android Keystore 加密保存，Windows 端保存在当前用户配置目录并尽量收紧 ACL。

## 2. 总体架构

```text
SMS 网络
   │ SMS_RECEIVED / PDU
   ▼
Android App
  SmsReceiver → 过滤/合并/去重 → CodeExtractor
                                  │
                                  ▼
                    规范 JSON + HMAC-SHA256
                                  │
                         Room 待发送队列
                                  │
                                  ▼
              ForegroundService / UsbAccessoryManager
                                  ║ USB AOA bulk
                                  ▼
Windows Python 服务
  AOA 枚举器 → 帧解码 → schema/HMAC/时效/重放校验
                                  │
                ┌─────────────────┴──────────────┐
                ▼                                ▼
          ACK 回传至手机                  内存 LatestCodeStore
                                                   │
                                                   ▼
                                FastAPI（仅 127.0.0.1）
                                                   │
                                                   ▼
                                      Playwright/Selenium
```

Android 内部以单一发送协调器保证同一 `messageId` 同时只有一个 ACK 等待任务。持久队列最多 100 条、最长保留 10 分钟；连接恢复时按创建时间重发。Windows 只在消息通过全部校验后写入内存并返回 `accepted` ACK。重复但此前已经接受的 `messageId` 仍返回幂等 ACK，避免 ACK 丢失导致手机永久重试。

## 3. Android 数据流与生命周期

1. `SmsReceiver` 调用 `Telephony.Sms.Intents.getMessagesFromIntent(intent)`，按数组顺序拼接同一广播中的长短信分段，提取发送方及最早接收时间。
2. 以发送方、时间窗口和正文摘要构成短期短信指纹，拦截广播重投；完整正文不落库。
3. 规则引擎先检查发送方白名单和必含关键词，再优先选择“验证码、校验码、动态码、OTP”附近的候选。候选无法唯一确定时拒绝发送。
4. 对同一发送方和验证码摘要实施 60 秒抑制。日志仅记录脱敏值。
5. 创建 UUID `messageId`、随机 nonce 和不可变消息载荷，签名后写入 Room，再交给 USB 协调器。
6. 发送后等待 3 秒 ACK；最多重试 3 次，间隔递增。重试沿用完全相同的 `messageId` 和已签名消息。
7. 收到有效 ACK 后标记送达并移除；断线或重试耗尽时保留在队列，受数量和 TTL 限制。

前台服务只维护 USB 会话、ACK 读取和队列调度。USB attach Intent 可唤起 Activity/服务处理授权；服务不使用无限轮询。BOOT_COMPLETED 仅在平台允许时启动合规前台服务，否则发布不含敏感信息的通知，请用户手动启动。

## 4. AOA 握手与重新枚举

### 4.1 Windows 将手机切换到 accessory 模式

Windows 枚举当前 USB 设备，对可能的 Android 设备逐个执行 AOA 探测，不依赖固定的原始手机 VID/PID：

1. 向 EP0 发送 vendor control IN 请求 `GET_PROTOCOL`：`request=51`、`value=0`、`index=0`、长度 2；返回 little-endian AOA 协议版本。
2. 版本受支持时，依次用 vendor control OUT `SEND_STRING`（`request=52`）发送 NUL 结尾 UTF-8 标识：

   | index | 值 |
   |---:|---|
   | 0 | `MyCompany` |
   | 1 | `SmsUsbForwarder` |
   | 2 | `SMS verification code USB forwarding accessory` |
   | 3 | `1.0` |
   | 4 | `https://localhost` |
   | 5 | `SMSUSB001` |

3. 发送 vendor control OUT `START_ACCESSORY`：`request=53`、`value=0`、`index=0`。
4. 原 USB 句柄随即失效。关闭资源并等待重新枚举，不把该异常当成进程失败。
5. 重新枚举后识别 Google AOA VID `0x18D1` 和 AOA 系列 PID；随后仍通过 descriptor 寻找具有 bulk IN 与 bulk OUT endpoint 的 interface，不能假定 interface number 或 endpoint 地址。
6. 必要时 detach kernel driver（Windows 通常无此步骤），claim interface；退出、断线及异常路径都 release interface、dispose resources。

切换后的 AOA 设备实例可能需要单独绑定 WinUSB/libusb 驱动。只选择明确的 AOA VID/PID 或对应接口，不替换手机正常的 Android Composite ADB/MTP 驱动。

### 4.2 Android 接收 accessory

Manifest 声明 `USB_ACCESSORY_ATTACHED` filter 及 accessory metadata。Activity 同时处理冷启动 Intent 和 `onNewIntent`；运行中的服务另行接收 detach/permission 事件。

Android 不假设普通插线后 `UsbManager.accessoryList` 立即非空。只有电脑完成 AOA 切换并重新枚举后，才从 attach Intent 或 `accessoryList` 获得匹配 accessory。无权限时使用唯一、不可变或可变标志符合当前 Android 版本要求的 `PendingIntent` 请求授权；授权后调用 `openAccessory`，从 `ParcelFileDescriptor.fileDescriptor` 建立输入输出流。

读写在 `Dispatchers.IO` 独立协程执行。detach、EOF、写失败和服务停止统一取消子任务，在 `finally` 中关闭流及 `ParcelFileDescriptor`。重新 attach 后重新创建整个会话，不复用旧文件描述符。

## 5. 线协议

### 5.1 帧格式

```text
+----------------------+---------------------------+
| 4-byte uint32 BE N   | N-byte strict UTF-8 JSON |
+----------------------+---------------------------+
```

- `N` 取值为 1..8192；0 或大于 8192 立即判为协议错误并断开当前会话。
- 接收端维护字节缓冲区，循环提取完整帧，正确处理拆包和粘包。
- JSON 必须严格 UTF-8 解码，不替换非法字节；必须是对象且通过对应消息模型校验。
- 一个坏会话被关闭并重新枚举，但不能使 Windows 服务进程退出。

### 5.2 sms_code 消息

```json
{
  "protocolVersion": 1,
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "type": "sms_code",
  "sender": "10690000",
  "code": "583921",
  "smsTextMasked": "您的验证码为 58****",
  "receivedAt": "2026-08-01T11:00:00+08:00",
  "sentAt": "2026-08-01T11:00:01+08:00",
  "nonce": "base64url-random-value",
  "hmac": "lowercase-hex-hmac-sha256"
}
```

约束：`protocolVersion` 必须为 1；`messageId` 是 UUID；时间是带时区的 RFC 3339/ISO 8601；nonce 至少来自 128 bit CSPRNG；`smsTextMasked` 不得含完整验证码或完整短信。Windows 对 `receivedAt/sentAt` 设置允许时钟偏差和最大消息年龄，并分别缓存近期 nonce 与 messageId。

### 5.3 规范 JSON 与 HMAC

签名输入是移除顶层 `hmac` 字段后的 JSON 对象，并按以下共同规则序列化：

- UTF-8 编码，无 BOM；
- 对象键按 Unicode code point 升序排列，所有嵌套对象同样处理；
- 无缩进，键值分隔符为 `:`，成员分隔符为 `,`，不得包含多余空白；
- 字符串使用标准 JSON 转义，非 ASCII Unicode 字符直接输出，不转为 `\uXXXX`；
- 本协议模型禁止浮点数、NaN/Infinity 和未声明字段；整数使用十进制最短形式。

即等价于 Python `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 结果；Android 实现须产生完全相同字节。HMAC 为 `HMAC-SHA256(sharedSecretBytes, canonicalBytes)`，输出 64 个小写十六进制字符。密钥按用户输入的 UTF-8 原始字节使用；设置界面明确禁止静默 trim。验证使用恒定时间比较。

### 5.4 ACK

```json
{
  "protocolVersion": 1,
  "type": "ack",
  "messageId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "receivedAt": "2026-08-01T11:00:02+08:00"
}
```

ACK 使用相同长度帧。它不携带验证码。第一版 ACK 严格按需求字段发送，不另加 HMAC；其安全性依赖已建立的本地物理 USB 通道，且 Android 只接受当前待确认 UUID 的 `accepted` ACK。未来若协议升级，可在 `protocolVersion=2` 中增加双向签名，不能无版本地改变 v1。

Windows 校验顺序为：帧长度 → UTF-8/JSON → schema/版本 → 时间有效性 → HMAC → nonce 未使用 → messageId 幂等判断 → 写入最新码 → 记录 nonce/messageId → ACK。为避免竞态，最后四步在同一锁保护的事务式临界区完成。

## 6. 本地 API 边界

FastAPI 固定绑定 `127.0.0.1`。`/health` 不返回秘密；验证码接口要求 Bearer token。`LatestCodeStore` 只在内存保存最新记录，默认 5 分钟过期，使用 condition/event 支持异步等待。`wait-code` 还接收请求验证码动作发生的起始时间，以排除旧验证码；`consume=true` 的读取和删除必须原子化。

## 7. 项目目录

```text
.
├── ARCHITECTURE.md
├── README.md
├── android_sms_usb_forwarder/
│   ├── settings.gradle.kts
│   ├── build.gradle.kts
│   ├── gradle.properties
│   ├── gradle/wrapper/
│   └── app/
│       ├── build.gradle.kts
│       ├── proguard-rules.pro
│       └── src/
│           ├── main/
│           │   ├── AndroidManifest.xml
│           │   ├── java/com/example/smsusbforwarder/
│           │   │   ├── SmsUsbApplication.kt
│           │   │   ├── MainActivity.kt
│           │   │   ├── data/{db,preferences,repository}/
│           │   │   ├── domain/{model,rules,security}/
│           │   │   ├── receiver/{SmsReceiver,BootReceiver}.kt
│           │   │   ├── service/UsbForwardService.kt
│           │   │   ├── usb/{UsbAccessoryManager,FrameCodec,AckCoordinator}.kt
│           │   │   └── ui/{main,settings,logs,theme}/
│           │   └── res/xml/accessory_filter.xml
│           └── test/java/com/example/smsusbforwarder/
│               ├── CodeExtractorTest.kt
│               ├── CanonicalJsonTest.kt
│               ├── HmacTest.kt
│               ├── FrameCodecTest.kt
│               ├── DedupeTest.kt
│               ├── AckCoordinatorTest.kt
│               └── QueueExpiryTest.kt
└── pc_receiver/
    ├── app/
    │   ├── main.py
    │   ├── config.py
    │   ├── logging_config.py
    │   ├── api/routes.py
    │   ├── models/messages.py
    │   ├── security/{hmac_utils,replay_guard}.py
    │   ├── storage/latest_code.py
    │   └── usb/{aoa,transport,protocol}.py
    ├── examples/playwright_login.py
    ├── tests/
    │   ├── test_protocol.py
    │   ├── test_hmac_utils.py
    │   ├── test_replay_guard.py
    │   ├── test_latest_code.py
    │   └── test_api.py
    ├── requirements.txt
    ├── pyproject.toml
    ├── README.md
    └── run.bat
```

## 8. 第一阶段验收决策

- AOA 原始设备不硬编码 VID/PID；AOA 状态识别标准 Google VID/PID，并用 descriptor 自动发现 interface/endpoints。
- USB 传输只有一种帧格式，双向共用；最大载荷固定 8192 字节。
- sms_code 的签名字节规则已跨语言固定，未知字段拒绝，避免不同 JSON 库产生歧义。
- ACK、重试、Room 队列和 Windows messageId 去重共同保证“至少一次传输、业务上至多一次接收”。
- 完整短信不离开瞬时处理内存；Room、日志和通知均不保存敏感正文。
- API 仅回环地址可见，验证码只驻留内存且可消费删除。

