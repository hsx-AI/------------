from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import atrust_auto_login
from scheduler_settings import load_scheduler_config, resolve_db_path


ROOT = Path(__file__).resolve().parent
ATRUST_CONFIG = ROOT / "atrust_config.json"
ECS_CONFIG = ROOT / "ecs_login_config.json"
RECEIVER_PYTHON = ROOT / "pc_receiver" / ".venv" / "Scripts" / "python.exe"
ECS_SYNC_SCRIPT = ROOT / "ecs_sync.py"


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


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


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


def load_atrust_login_args(phone_override: str | None = None) -> tuple[str, int, str | None]:
    atrust_config = load_json(ATRUST_CONFIG)
    phone = (phone_override or str(atrust_config.get("phone", ""))).strip()
    if not phone or phone.startswith("在这里填写"):
        raise RuntimeError("请在 atrust_config.json 中填写 phone，或使用 --phone 参数")
    timeout = int(atrust_config.get("smsTimeoutSeconds", 120))
    if not 1 <= timeout <= 300:
        raise RuntimeError("atrust_config.json 的 smsTimeoutSeconds 必须在 1 到 300 之间")
    sender = str(atrust_config.get("smsSenderContains", "")).strip() or None
    return phone, timeout, sender


def run_ecs_sync(*, prefer_session: bool, db_path: Path, keep_excel: bool) -> None:
    if not RECEIVER_PYTHON.exists():
        raise RuntimeError(f"找不到接收器虚拟环境 Python：{RECEIVER_PYTHON}")
    command = [str(RECEIVER_PYTHON), str(ECS_SYNC_SCRIPT), "--db", str(db_path)]
    if prefer_session:
        command.append("--prefer-session")
    if not keep_excel:
        command.append("--delete-excel")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ECS 同步失败，退出码 {completed.returncode}")


def run_full_login_cycle(
    phone: str,
    timeout: int,
    sender: str | None,
    db_path: Path,
    keep_excel: bool,
) -> None:
    log("执行完整登录：aTrust + AE 平台")
    atrust_auto_login.run(phone, timeout, sender)
    run_ecs_sync(prefer_session=False, db_path=db_path, keep_excel=keep_excel)


def run_one_cycle(
    phone: str,
    timeout: int,
    sender: str | None,
    *,
    prefer_saved_session: bool,
    db_path: Path,
    keep_excel: bool,
) -> None:
    validate_ecs_config()
    if prefer_saved_session:
        try:
            log("优先尝试已保存 AE 会话同步")
            run_ecs_sync(prefer_session=True, db_path=db_path, keep_excel=keep_excel)
            return
        except Exception as exc:
            log(f"会话同步失败，将重新完整登录: {exc}")
    run_full_login_cycle(phone, timeout, sender, db_path, keep_excel)


def sleep_until_next(interval_minutes: float) -> None:
    total_seconds = max(1, int(interval_minutes * 60))
    log(f"等待下一轮同步，间隔 {interval_minutes:g} 分钟（{total_seconds} 秒）")
    deadline = time.monotonic() + total_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="定时同步 AE 协调平台 Excel 到 SQLite")
    parser.add_argument("--phone", help="覆盖 atrust_config.json 中的 phone")
    parser.add_argument("--once", action="store_true", help="只跑一轮后退出")
    parser.add_argument("--no-elevate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="本轮强制完整登录，不优先复用会话",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if os.name == "nt" and not args.no_elevate and not is_admin():
        print("正在请求管理员权限，以便启动 USB 短信接收服务……", flush=True)
        relaunch_as_admin()
        return 0

    if not ECS_CONFIG.exists():
        raise RuntimeError(f"找不到配置文件：{ECS_CONFIG}")
    phone, timeout, sender = load_atrust_login_args(args.phone)

    cycle_index = 0
    try:
        while True:
            cycle_index += 1
            config = load_scheduler_config()
            db_path = resolve_db_path(config)
            keep_excel = bool(config.get("keepDownloadedExcel", True))
            prefer_session = bool(config.get("preferSavedSession", True)) and not args.force_login
            interval = float(config.get("intervalMinutes", 60))
            if interval <= 0:
                raise RuntimeError("scheduler_config.json 的 intervalMinutes 必须大于 0")

            if cycle_index == 1 and not bool(config.get("runImmediately", True)):
                sleep_until_next(interval)

            print(f"\n=== 定时同步第 {cycle_index} 轮 ===", flush=True)
            try:
                run_one_cycle(
                    phone,
                    timeout,
                    sender,
                    prefer_saved_session=prefer_session,
                    db_path=db_path,
                    keep_excel=keep_excel,
                )
                log(f"第 {cycle_index} 轮同步完成")
            except Exception as exc:
                log(f"第 {cycle_index} 轮同步失败: {exc}")

            if args.once:
                return 0
            args.force_login = False
            sleep_until_next(interval)
    finally:
        atrust_auto_login.stop_started_receiver()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已停止定时同步", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        input("按 Enter 键退出……")
        raise SystemExit(1)
