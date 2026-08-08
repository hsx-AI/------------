# Windows Python AOA Receiver

Windows 端通过 libusb/pyusb 将 Android 手机切换到 Android Open Accessory 模式，持续接收长度前缀 JSON，完成 schema、时间、HMAC、nonce 和 messageId 校验，向手机回 ACK，并通过仅监听回环地址的 FastAPI 提供最新验证码。

## 1. 目录

```text
pc_receiver/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── logging_config.py
│   ├── api/routes.py
│   ├── models/messages.py
│   ├── security/{hmac_utils,replay_guard}.py
│   ├── storage/latest_code.py
│   └── usb/{aoa,protocol,receiver,transport}.py
├── examples/playwright_login.py
├── tests/
├── requirements.txt
├── pyproject.toml
├── setup.bat
└── run.bat
```

## 2. Python 与依赖安装

要求 Python 3.12 或更高版本。当前已在 Python 3.13.2 上验证。

```powershell
cd "E:\Desktop\tuixiu_protect\汽发工艺核电平台数据获取\pc_receiver"
.\setup.bat
```

或者手动安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements.txt
```

`libusb-package` 会在虚拟环境中提供 Windows libusb DLL，AOA 枚举器会显式使用该 backend，无需把 DLL 复制到系统目录。

## 3. 配置共享密钥和 API Token

先在 Android App 设置页输入一段足够长的共享密钥。电脑端执行：

```powershell
.\.venv\Scripts\python.exe -m app.main set-secret
```

终端会以隐藏输入方式读取密钥。不要在密钥前后添加空格；Android 和电脑使用逐字节相同的 UTF-8 值。Windows 端通过当前用户的 DPAPI 加密后保存，不把明文密钥写入配置文件。

首次运行随机生成本地 API Token。查看配置路径和 Token：

```powershell
.\.venv\Scripts\python.exe -m app.main show-config
```

默认配置位于：

```text
%LOCALAPPDATA%\SmsUsbForwarder\config.json
```

程序会用 `icacls` 尽量把配置目录和文件 ACL 限制为当前用户。日志绝不打印 Token、共享密钥或完整验证码。

也可以只为当前进程设置共享密钥而不持久化：

```powershell
$env:SMSUSB_SHARED_SECRET = "与手机完全相同的密钥"
.\run.bat
```

## 4. 启动服务

```powershell
.\run.bat
```

`run.bat` 会自动打开本地可视化控制台：

```text
http://127.0.0.1:8765/
```

控制台提供：

- API 和 USB accessory 实时连接状态；
- 最近一次有效消息时间；
- 自动建立的本地页面安全会话，无需手工输入 Token；
- 最新验证码读取、显示/隐藏、复制和原子消费；
- 按发送方等待新验证码并支持取消；
- 当前页面生命周期内的操作事件记录。

验证码默认只显示末两位。首页会设置一个仅当前服务进程有效、最长 8 小时的 `HttpOnly`、`SameSite=Strict` Cookie，网页无需看到或输入 API Token；页面响应设置为禁止缓存。独立自动化脚本仍使用 Bearer Token。

API 固定监听：

```text
http://127.0.0.1:8765
```

不会监听 `0.0.0.0`。USB 断开、非法消息或一次枚举失败不会退出进程；后台线程会释放 interface/设备资源并重新枚举。

## 5. Windows WinUSB/Zadig 驱动

### AOA 重新枚举后的设备

手机收到 `START_ACCESSORY` 后会断开并重新枚举。AOA 设备常见标识为 Google VID `18D1`、PID `2D00` 到 `2D05`。

1. 下载并运行 Zadig，菜单选择 `Options → List All Devices`。
2. 在手机已经切换到 AOA 状态后，选择 VID 为 `18D1`、PID 为 `2D00`～`2D05` 的新设备或其 accessory interface。
3. 右侧目标驱动选择 `WinUSB`，执行安装/替换。
4. 拔插手机并重新启动电脑端服务。

### 初始手机状态

电脑必须先通过手机初始 USB 状态的 EP0 发送 AOA 控制请求。libusb 需要 Windows 允许访问相应设备/interface。优先保留现有厂商驱动并直接尝试运行；如果无法读取 AOA protocol：

- 只对明确识别的单个 vendor-specific interface 绑定 WinUSB；
- 不要选择 USB Composite Device 父节点；
- 不要批量替换 Android Composite ADB Interface、MTP 或所有手机接口；
- 改动前在设备管理器记录原驱动提供商，以便需要时执行“更新驱动程序”恢复厂商/Google 驱动。

不同手机的初始 composite interface 布局不同。若没有可安全单独绑定的 vendor interface，先保留 ADB/MTP 驱动并根据设备管理器硬件 ID进行针对性处理，避免为了 AOA 破坏日常 ADB/MTP。

## 6. AOA 握手实现

`app/usb/aoa.py` 执行：

1. 枚举 USB 设备并尝试 `GET_PROTOCOL`（request 51）；
2. 发送 manufacturer、model、description、version、URI、serial（request 52）；
3. 发送 `START_ACCESSORY`（request 53）；
4. 关闭原设备资源，等待手机重新枚举；
5. 识别 `18D1:2D00`～`18D1:2D05`；
6. 遍历 descriptor，自动寻找同时具有 bulk IN/OUT 的 interface；
7. claim interface 并启动接收，不硬编码 interface number 或 endpoint 地址。

## 7. API 使用

健康检查不需要 Token：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

读取最新验证码：

```powershell
$token = "show-config 显示的 Token"
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:8765/api/latest-code -Headers $headers
```

读取后立即消费删除：

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/latest-code?consume=true" -Headers $headers
```

等待新验证码，超时返回 HTTP 408：

```powershell
$body = @{
    timeoutSeconds = 120
    senderContains = "1069"
    after = [DateTimeOffset]::UtcNow.ToString("o")
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri http://127.0.0.1:8765/api/wait-code `
    -Method Post `
    -Headers $headers `
    -ContentType application/json `
    -Body $body
```

验证码只保存在内存，默认 5 分钟过期。服务退出后不会恢复验证码；成功的等待接口会原子消费该验证码。

## 8. Playwright 示例

示例只包含通用占位选择器：

```text
#request-code
#verification-code
#login-button
```

安装 Chromium：

```powershell
.\.venv\Scripts\playwright.exe install chromium
```

运行：

```powershell
$env:SMSUSB_API_TOKEN = "本地 API Token"
$env:LOGIN_URL = "你的内部测试页面地址"
.\.venv\Scripts\python.exe .\examples\playwright_login.py
```

示例在点击“获取验证码”前记录 UTC 时间，`wait-code` 只接受该时间之后的新验证码，并在成功读取后消费，避免复用旧码。

## 9. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

18 项测试覆盖长度帧拆包/粘包、非法 UTF-8、8192 字节限制、规范 JSON、Android/Python HMAC 黄金向量、nonce 重放、messageId 幂等、时间存储、过期/消费、API 鉴权/408 和 AOA control transfer 顺序。

## 10. 联调步骤

1. 手机 App 和电脑配置相同共享密钥。
2. 手机授予短信与通知权限，启动前台服务。
3. USB 数据线连接手机，保持手机解锁。
4. 运行 `run.bat`，观察日志是否出现 `Requested AOA mode`。
5. 手机会重新枚举；确认 accessory 授权弹窗。
6. 如 Windows 无法打开重新枚举的设备，只为 AOA VID/PID 安装 WinUSB。
7. 日志出现 `AOA USB accessory connected` 后，在手机点“测试发送”。
8. 调用 `/api/latest-code`，确认收到 `583921`；手机日志应出现 ACK 已送达。

## 11. 排障

- **没有 UsbAccessory / 手机不弹授权**：确认电脑日志是否成功读取 AOA protocol 并发送 `START_ACCESSORY`；更换支持数据传输的 USB 线和直接连接的 USB 端口。
- **重新枚举失败**：在设备管理器按硬件 ID查找新出现的 `VID_18D1&PID_2Dxx`；重新插拔，并避免 USB Hub。
- **No backend available**：确认在项目虚拟环境中安装了 `libusb-package`，并使用 `.venv` 里的 Python 启动。
- **Access denied / claim interface 失败**：为准确的 AOA interface 安装 WinUSB；关闭可能占用该 interface 的其他程序。
- **HMAC 无效**：重新执行 `set-secret`，确保手机和电脑密钥完全相同，尤其检查首尾空格和输入法字符。
- **时间窗口无效**：让 Windows 和 Android 开启系统自动校时及时区设置。
- **API 401**：重新运行 `show-config` 获取当前 Token，请勿使用 HMAC 共享密钥作为 API Token。
- **查看日志**：`%LOCALAPPDATA%\SmsUsbForwarder\receiver.log`，日志仅包含连接、校验结果和验证码末两位。
- **SDK/驱动工具版本差异**：这与 Python 接收器无关；电脑端只依赖 WinUSB/libusb，不依赖 Android SDK。
