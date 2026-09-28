from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import atrust_auto_login


ROOT = Path(__file__).resolve().parent
ATRUST_CONFIG = ROOT / "atrust_config.json"
ECS_CONFIG = ROOT / "ecs_login_config.json"
RECEIVER_PYTHON = ROOT / "pc_receiver" / ".venv" / "Scripts" / "python.exe"
ECS_SCRIPT = ROOT / "ecs_auto_login.py"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    parameters = subprocess.list2cmdline([str(Path(__file__).resolve()), *sys.argv[1:]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, parameters, str(ROOT), 1
    )
    if result <= 32:
        raise ctypes.WinError(result)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"找不到配置文件：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{path.name} 顶层必须是 JSON 对象")
    return data


def validate_ecs_config() -> None:
    config = load_json(ECS_CONFIG)
    for key in ("username", "password"):
        value = str(config.get(key, "")).strip()
        if not value or value.startswith("在这里填写"):
            raise RuntimeError(f"请在 ecs_login_config.json 中填写 {key}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键登录 aTrust 和 AE 协调平台")
    parser.add_argument("--phone", help="覆盖 atrust_config.json 中的 phone")
    parser.add_argument("--no-elevate", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if os.name == "nt" and not args.no_elevate and not is_admin():
        print("正在请求管理员权限，以便启动 USB 短信接收服务……", flush=True)
        relaunch_as_admin()
        return 0

    atrust_config = load_json(ATRUST_CONFIG)
    phone = (args.phone or str(atrust_config.get("phone", ""))).strip()
    if not phone or phone.startswith("在这里填写"):
        raise RuntimeError("请在 atrust_config.json 中填写 phone，或使用 --phone 参数")
    timeout = int(atrust_config.get("smsTimeoutSeconds", 120))
    if not 1 <= timeout <= 300:
        raise RuntimeError("atrust_config.json 的 smsTimeoutSeconds 必须在 1 到 300 之间")
    sender = str(atrust_config.get("smsSenderContains", "")).strip() or None

    # 在发送第一条短信前检查第二阶段配置，避免流程进行一半才发现缺少凭据。
    validate_ecs_config()

    try:
        print("\n=== 第一阶段：登录 aTrust ===", flush=True)
        atrust_auto_login.run(phone, timeout, sender)

        if not RECEIVER_PYTHON.exists():
            raise RuntimeError(f"找不到接收器虚拟环境 Python：{RECEIVER_PYTHON}")

        print("\n=== 第二阶段：登录 AE 协调平台 ===", flush=True)
        completed = subprocess.run(
            [str(RECEIVER_PYTHON), str(ECS_SCRIPT)], cwd=ROOT, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(f"AE 平台登录阶段失败，退出码 {completed.returncode}")

        print("\n全部登录流程已完成。", flush=True)
        return 0
    finally:
        atrust_auto_login.stop_started_receiver()


if __name__ == "__main__":
    try:
        exit_code = main()
        input("\n流程已完成。按 Enter 键退出……")
        raise SystemExit(exit_code)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        input("按 Enter 键退出……")
        raise SystemExit(1)
