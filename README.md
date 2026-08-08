# SMS USB Forwarder

这是“安卓短信验证码经 Android Open Accessory USB 转发至 Windows”的工程仓库。

第一阶段设计见 [ARCHITECTURE.md](ARCHITECTURE.md)：包括系统边界、AOA 握手与重新枚举、长度前缀 JSON 协议、规范化签名规则、ACK/去重语义及完整目标目录。

第二阶段 Android 工程位于 [android_sms_usb_forwarder](android_sms_usb_forwarder/README.md)。第三阶段 Windows Python 接收器、FastAPI、Playwright 示例、测试与联调指南位于 [pc_receiver](pc_receiver/README.md)。
