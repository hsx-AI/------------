# aTrust 一键短信登录

双击 `login_atrust.bat`，通过 Windows 管理员确认并输入手机号后，程序会自动：

1. 启动或复用 `pc_receiver` USB 短信接收服务；
2. 打开 aTrust 客户端并填写手机号；
3. 点击“立即获取”，仅等待本次请求之后的新验证码；
4. 从本机受保护的 API 获取并消费验证码；
5. 填写验证码并点击“登录”。

也可以在 PowerShell 中运行：

```powershell
python .\atrust_auto_login.py --phone 你的手机号
```

如需固定配置（避免每次输入）：

```powershell
$env:ATRUST_PHONE = "你的手机号"
.\login_atrust.bat
```

可用参数：`--timeout 120` 设置等待秒数，`--sender 1069` 限定短信发送方。

## 前提

- `pc_receiver\.venv` 已完成安装；
- 手机 USB 已连接、解锁，并已允许 Android Accessory 连接；
- 手机端与 PC 接收器已配置相同的 HMAC 共享密钥；
- 登录期间不要操作鼠标和键盘，脚本需要把 aTrust 窗口置于前台。

批处理会申请管理员权限，是因为现有 `SmsUsbForwarder` 配置及日志目录的 ACL 只允许提升后的进程写入；aTrust 本身不会被修改。

API Token 自动从 `%LOCALAPPDATA%\SmsUsbForwarder\config.json` 读取，不写入本项目。验证码只保存在接收服务内存中，并在读取时原子消费。

## AE 协调平台自动登录

首次使用时，把 `ecs_login_config.example.json` 复制为 `ecs_login_config.json`，填写：

- `username`：AE 平台账号；
- `password`：AE 平台密码；
- `verificationPasswordEncoding`：验证码接口对密码的预处理方式；含特殊字符时使用 `url`；
- `smsSenderContains`：可留空；如需避免混淆短信，可填写发送号码的一部分；

在 `atrust_config.json` 中填写 aTrust 登录手机号，然后运行统一主程序：

```powershell
python .\main.py
```

`main.py` 会自动申请管理员权限，并依次完成 aTrust 登录、等待隧道可用、通过纯 HTTP 请求获取 AE 平台验证码、提交 CAS 加密登录并保存 ECS 会话 Cookie。第二阶段不需要打开或控制浏览器。

`ecs_login_config.json` 已加入 `.gitignore`，不会被 Git 跟踪。它仍是本地明文配置，请限制该文件的 Windows 访问权限，不要发送给他人。
