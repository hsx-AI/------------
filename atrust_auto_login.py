from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CLIENT_EXE = Path(r"C:\Program Files (x86)\Sangfor\aTrust\aTrustTray\aTrustTray.exe")
RECEIVER_DIR = ROOT / "pc_receiver"
RECEIVER_PYTHON = RECEIVER_DIR / ".venv" / "Scripts" / "python.exe"
RECEIVER_CONFIG = Path(os.environ.get("LOCALAPPDATA", "")) / "SmsUsbForwarder" / "config.json"
API_URL = "http://127.0.0.1:8765"

# Coordinates measured from the currently installed frameless aTrust window.
# DPI awareness above makes these true physical client coordinates.  The
# bottom diagnostics toolbar accounts for the height difference from the
# earlier reference screenshot.
REFERENCE_SIZE = (921, 570)
PHONE_POINT = (744, 197)
REQUEST_POINT = (840, 257)
# After “立即获取” succeeds, a green notification banner is inserted above
# the form and shifts all fields below it down by about 55 pixels.
CODE_POINT = (700, 312)
LOGIN_POINT = (706, 411)
AE_PLATFORM_POINT = (280, 174)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD

# Mouse coordinates are physical pixels.  Without per-monitor DPI awareness,
# Windows virtualizes GetClientRect/ClientToScreen but not all input paths in
# the same way, which shifts clicks when display scaling is 125%/150%.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except (AttributeError, OSError):
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass

SW_RESTORE = 9
WM_CLOSE = 0x0010
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_A = 0x41


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    # Windows requires INPUT to have the size of its largest union member,
    # even when this program only sends keyboard events.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def api_request(path: str, token: str | None = None, body: dict | None = None, timeout: int = 5) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API_URL + path, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def ensure_receiver() -> str:
    try:
        api_request("/health", timeout=2)
    except (OSError, urllib.error.URLError):
        if not RECEIVER_PYTHON.exists():
            raise RuntimeError(f"短信接收器虚拟环境不存在，请先运行: {RECEIVER_DIR / 'setup.bat'}")
        log("启动 USB 短信接收服务")
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        receiver_process = subprocess.Popen(
            [str(RECEIVER_PYTHON), "-m", "app.main", "run"],
            cwd=RECEIVER_DIR,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if receiver_process.poll() is not None:
                raise RuntimeError(
                    "短信接收服务启动后立即退出。当前配置目录可能要求管理员权限；请双击 login_atrust.bat 运行"
                )
            time.sleep(0.3)
            try:
                api_request("/health", timeout=0.5)
                break
            except (OSError, urllib.error.URLError):
                pass
        else:
            raise RuntimeError("短信接收服务启动失败，请检查 pc_receiver 日志")

    if not RECEIVER_CONFIG.exists():
        raise RuntimeError(f"找不到短信接收器配置: {RECEIVER_CONFIG}")
    token = json.loads(RECEIVER_CONFIG.read_text(encoding="utf-8")).get("apiToken")
    if not token:
        raise RuntimeError("短信接收器配置中没有 apiToken")
    health = api_request("/health", timeout=2)
    if not health.get("usbConnected"):
        log("警告：手机 USB 尚未显示为已连接；仍将等待验证码，请确认手机已解锁并授权配件连接")
    return token


def find_window() -> int | None:
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == "aTrust" and user32.IsWindowVisible(hwnd):
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                if rect.right >= 700 and rect.bottom >= 400:
                    found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def open_client(timeout: int = 20) -> int:
    if not CLIENT_EXE.exists():
        raise RuntimeError(f"找不到 aTrust 客户端: {CLIENT_EXE}")
    subprocess.Popen([str(CLIENT_EXE)])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = find_window()
        if hwnd:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            time.sleep(1)
            return hwnd
        time.sleep(0.5)
    raise RuntimeError("未找到 aTrust 登录窗口")


def client_point(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right, rect.bottom
    if width < 700 or height < 400:
        raise RuntimeError(f"aTrust 窗口尺寸异常: {width}x{height}")
    # aTrust adds/removes its bottom diagnostics toolbar dynamically.  That
    # changes the reported window height, while the login form itself remains
    # at fixed client coordinates.  Scaling by the whole client size therefore
    # moves the code/login clicks upward into the preceding controls.
    if point[0] >= width or point[1] >= height:
        raise RuntimeError(f"目标控件坐标 {point} 超出 aTrust 客户区 {width}x{height}")
    pt = wintypes.POINT(point[0], point[1])
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def click(hwnd: int, point: tuple[int, int]) -> None:
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    x, y = client_point(hwnd, point)
    user32.SetCursorPos(x, y)
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.12)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.55)


def pixel_color(hwnd: int, point: tuple[int, int]) -> tuple[int, int, int]:
    x, y = client_point(hwnd, point)
    dc = user32.GetDC(0)
    if not dc:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        color = gdi32.GetPixel(dc, x, y)
    finally:
        user32.ReleaseDC(0, dc)
    if color == 0xFFFFFFFF:
        raise RuntimeError("Cannot read aTrust window pixel")
    return color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF


def login_button_is_blue(hwnd: int) -> bool:
    red, green, blue = pixel_color(hwnd, LOGIN_POINT)
    return blue >= 180 and blue > red * 1.35 and blue > green * 1.15


def wait_for_workspace(timeout: int = 60) -> int:
    log("Waiting for aTrust workspace")
    deadline = time.monotonic() + timeout
    non_blue_since: float | None = None
    while time.monotonic() < deadline:
        hwnd = find_window()
        if not hwnd:
            non_blue_since = None
            time.sleep(0.5)
            continue
        try:
            workspace_visible = not login_button_is_blue(hwnd)
        except Exception:
            workspace_visible = False
        if workspace_visible:
            non_blue_since = non_blue_since or time.monotonic()
            if time.monotonic() - non_blue_since >= 2:
                return hwnd
        else:
            non_blue_since = None
        time.sleep(0.4)
    raise TimeoutError("aTrust workspace did not appear within 60 seconds")


def open_ae_platform() -> None:
    # Successful authentication may minimize the client back to its tray.
    # Launching the tray executable again restores the existing main window.
    open_client()
    hwnd = wait_for_workspace()
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1)
    log("Clicking AE platform tile")
    click(hwnd, AE_PLATFORM_POINT)
    time.sleep(3)


def keyboard(vk: int, up: bool = False) -> None:
    inp = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)))
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def replace_text(hwnd: int, point: tuple[int, int], text: str) -> None:
    click(hwnd, point)
    # The embedded browser sometimes accepts the mouse click visually before
    # its input element has keyboard focus.  Waiting here prevents the first
    # digit from being swallowed.
    time.sleep(0.8)
    # A second click is intentional: the first can merely activate the
    # Chromium-based child surface after the receiver wait returns.
    click(hwnd, point)
    time.sleep(0.45)
    keyboard(VK_CONTROL)
    keyboard(VK_A)
    keyboard(VK_A, up=True)
    keyboard(VK_CONTROL, up=True)
    time.sleep(0.35)
    for char in text:
        code = ord(char)
        down = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
        up = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
        inputs = (INPUT * 2)(down, up)
        if user32.SendInput(2, inputs, ctypes.sizeof(INPUT)) != 2:
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.07)
    time.sleep(0.6)


def wait_for_code(token: str, after: datetime, timeout: int, sender: str | None) -> str:
    body = {"timeoutSeconds": timeout, "after": after.isoformat(), "senderContains": sender or None}
    try:
        result = api_request("/api/wait-code", token=token, body=body, timeout=timeout + 10)
    except urllib.error.HTTPError as exc:
        if exc.code == 408:
            raise TimeoutError(f"{timeout} 秒内未收到新验证码") from exc
        raise RuntimeError(f"短信接收接口返回 HTTP {exc.code}") from exc
    code = str(result.get("code", ""))
    if not code:
        raise RuntimeError("短信接收接口没有返回验证码")
    return code


def run(phone: str, timeout: int, sender: str | None) -> None:
    if not phone.isdigit() or not 6 <= len(phone) <= 15:
        raise ValueError("手机号必须是 6 到 15 位数字（中国大陆号码直接填写 11 位号码）")
    token = ensure_receiver()
    log("打开 aTrust 登录窗口")
    hwnd = open_client()
    replace_text(hwnd, PHONE_POINT, phone)
    requested_after = datetime.now(timezone.utc)
    log("请求短信验证码")
    click(hwnd, REQUEST_POINT)
    log(f"等待手机转发新验证码（最长 {timeout} 秒）")
    code = wait_for_code(token, requested_after, timeout, sender)
    log("已收到验证码，正在填写并登录")
    hwnd = find_window()
    if not hwnd:
        raise RuntimeError("等待验证码期间 aTrust 登录窗口已关闭")
    replace_text(hwnd, CODE_POINT, code)
    click(hwnd, LOGIN_POINT)
    log("aTrust login submitted")
    time.sleep(3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键登录 Sangfor aTrust 短信认证客户端")
    parser.add_argument("--phone", default=os.environ.get("ATRUST_PHONE"), help="登录手机号；也可设置 ATRUST_PHONE")
    parser.add_argument("--timeout", type=int, default=120, choices=range(1, 301), metavar="1-300")
    parser.add_argument("--sender", default=os.environ.get("ATRUST_SMS_SENDER"), help="可选：短信发送方包含的文字/号码")
    args = parser.parse_args()
    if not args.phone:
        parser.error("请使用 --phone 指定手机号，或设置 ATRUST_PHONE 环境变量")
    return args


if __name__ == "__main__":
    try:
        options = parse_args()
        run(options.phone, options.timeout, options.sender)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
