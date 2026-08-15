from __future__ import annotations

import argparse
import ctypes
import json
import math
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

# Coordinates measured from a 921x570 frameless aTrust client.  At runtime
# they are scaled by the current client width, which follows the window's DPI
# while remaining unaffected by the optional bottom diagnostics toolbar.
REFERENCE_SIZE = (921, 570)
PHONE_POINT = (744, 197)
REQUEST_POINT = (840, 257)
# After “立即获取” succeeds, a green notification banner is inserted above
# the form and shifts all fields below it down by about 55 pixels.
CODE_POINT = (700, 312)
LOGIN_POINT = (706, 411)
AE_PLATFORM_POINT = (280, 174)

CONTROL_LABELS = {
    "phone": "手机号输入框",
    "request": "获取验证码按钮",
    "code": "验证码输入框",
    "login": "登录按钮",
    "ae_platform": "AE 平台入口",
}
CONTROL_KEYWORDS = {
    "phone": ("手机号", "手机号码", "phone", "mobile"),
    "request": ("立即获取", "获取验证码", "发送验证码", "send code", "get code"),
    "code": ("验证码", "校验码", "动态码", "verification code", "otp"),
    "login": ("登录", "登陆", "log in", "login"),
    "ae_platform": ("ae 协调平台", "ae平台", "协调平台"),
}
CONTROL_TYPES = {
    "phone": ("edit",),
    "request": ("button", "hyperlink"),
    "code": ("edit",),
    "login": ("button",),
    "ae_platform": ("button", "listitem", "hyperlink"),
}
# Buttons in this client use Sangfor blue.  Searching for that color around
# the scaled reference point corrects small layout shifts without needing a
# reference screenshot or OCR package.
VISUAL_BLUE_SEARCH = {
    "request": (130, 55),
    "login": (170, 80),
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL

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
    # aTrust's native SSL/proxy/defender processes write verbose diagnostics to
    # every inherited console handle.  Detaching the GUI process and redirecting
    # all three standard streams keeps those vendor logs out of this program's
    # console while preserving our own progress messages and exceptions.
    creation_flags = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(CLIENT_EXE)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
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


def client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right, rect.bottom
    if width < 700 or height < 400:
        raise RuntimeError(f"aTrust 窗口尺寸异常: {width}x{height}")
    return width, height


def scaled_reference_point(width: int, point: tuple[int, int]) -> tuple[int, int]:
    """Scale a reference client point using width, which tracks aTrust DPI."""
    scale = width / REFERENCE_SIZE[0]
    return round(point[0] * scale), round(point[1] * scale)


def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    width, height = client_size(hwnd)
    if not 0 <= point[0] < width or not 0 <= point[1] < height:
        raise RuntimeError(f"目标控件坐标 {point} 超出 aTrust 客户区 {width}x{height}")
    pt = wintypes.POINT(*point)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def client_point(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """Convert a reference-size client point to a physical screen point."""
    width, _height = client_size(hwnd)
    return client_to_screen(hwnd, scaled_reference_point(width, point))


def client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    width, height = client_size(hwnd)
    left, top = client_to_screen(hwnd, (0, 0))
    return left, top, left + width, top + height


def enumerate_uia_controls(hwnd: int) -> list[dict]:
    """Read UI Automation descendants without requiring third-party modules."""
    script = r"""
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]__HWND__)
if ($null -eq $root) { exit 0 }
$items = @($root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
))
$result = foreach ($item in $items) {
    try {
        $current = $item.Current
        [PSCustomObject]@{
            type = $current.ControlType.ProgrammaticName
            name = $current.Name
            automationId = $current.AutomationId
            className = $current.ClassName
            x = $current.BoundingRectangle.X
            y = $current.BoundingRectangle.Y
            width = $current.BoundingRectangle.Width
            height = $current.BoundingRectangle.Height
            focusable = $current.IsKeyboardFocusable
            enabled = $current.IsEnabled
        }
    } catch {}
}
if ($null -ne $result) { @($result) | ConvertTo-Json -Compress -Depth 3 }
""".replace("__HWND__", str(hwnd))
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            creationflags=creation_flags,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        result = json.loads(completed.stdout)
        return result if isinstance(result, list) else [result]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def choose_uia_control(
    controls: list[dict],
    role: str,
    expected_screen: tuple[int, int],
    bounds: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    """Choose an accessible control by semantics, type, and expected position."""
    left, top, right, bottom = bounds
    keywords = CONTROL_KEYWORDS.get(role, ())
    preferred_types = CONTROL_TYPES.get(role, ())
    best: tuple[float, tuple[int, int]] | None = None
    for control in controls:
        try:
            x = float(control.get("x", 0))
            y = float(control.get("y", 0))
            width = float(control.get("width", 0))
            height = float(control.get("height", 0))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            continue
        if width < 8 or height < 8 or not control.get("enabled", True):
            continue
        center = round(x + width / 2), round(y + height / 2)
        if not left <= center[0] < right or not top <= center[1] < bottom:
            continue

        control_type = str(control.get("type", "")).rsplit(".", 1)[-1].lower()
        searchable = " ".join(
            str(control.get(key, "")) for key in ("name", "automationId", "className")
        ).lower()
        keyword_match = any(keyword in searchable for keyword in keywords)
        type_match = any(preferred in control_type for preferred in preferred_types)
        if not keyword_match and not type_match:
            continue
        distance = math.dist(center, expected_screen)
        score = (120 if keyword_match else 0) + (35 if type_match else 0) - distance / 20
        if control.get("focusable"):
            score += 5
        if best is None or score > best[0]:
            best = score, center
    return best[1] if best else None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_client_bgra(hwnd: int) -> tuple[int, int, bytes] | None:
    """Capture the aTrust client even when another window partly covers it."""
    width, height = client_size(hwnd)
    window_dc = user32.GetDC(hwnd)
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height) if memory_dc else None
    old_object = gdi32.SelectObject(memory_dc, bitmap) if bitmap else None
    try:
        if not memory_dc or not bitmap:
            return None
        rendered = user32.PrintWindow(hwnd, memory_dc, 0x00000003)  # client + full content
        if not rendered:
            rendered = gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, 0x00CC0020)
        if not rendered:
            return None
        header = BITMAPINFOHEADER(
            ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0
        )
        pixels = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0
        ):
            return None
        return width, height, pixels.raw
    finally:
        if old_object:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def visually_refine_blue_control(
    hwnd: int, role: str, expected_client: tuple[int, int]
) -> tuple[int, int] | None:
    search = VISUAL_BLUE_SEARCH.get(role)
    if not search:
        return None
    captured = capture_client_bgra(hwnd)
    if not captured:
        return None
    width, height, pixels = captured
    scale = width / REFERENCE_SIZE[0]
    radius_x, radius_y = round(search[0] * scale), round(search[1] * scale)
    x0 = max(0, expected_client[0] - radius_x)
    x1 = min(width, expected_client[0] + radius_x + 1)
    y0 = max(0, expected_client[1] - radius_y)
    y1 = min(height, expected_client[1] + radius_y + 1)
    sum_x = sum_y = count = 0
    # Sampling every other pixel is enough for both filled buttons and blue text.
    for y in range(y0, y1, 2):
        row = y * width * 4
        for x in range(x0, x1, 2):
            index = row + x * 4
            blue, green, red = pixels[index], pixels[index + 1], pixels[index + 2]
            if blue >= 155 and blue >= red + 55 and blue >= green + 30:
                sum_x += x
                sum_y += y
                count += 1
    blue_center = (round(sum_x / count), round(sum_y / count)) if count >= 8 else None
    if role == "request":
        # The blue glyphs can sit slightly above the clickable row center at
        # some font/DPI combinations.  Use the code input's long gray top and
        # bottom borders to derive the exact vertical center, while retaining
        # the blue “立即获取” text for the horizontal coordinate.
        row_center = detect_input_row_center(
            width, height, pixels, expected_client, scale
        )
        if row_center is not None:
            return (blue_center[0] if blue_center else expected_client[0]), row_center
    return blue_center


def detect_input_row_center(
    width: int,
    height: int,
    pixels: bytes,
    expected_client: tuple[int, int],
    scale: float,
) -> int | None:
    """Find the code input rectangle and return its geometric vertical center."""
    expected_x, expected_y = expected_client
    x0 = max(0, expected_x - round(360 * scale))
    x1 = min(width, expected_x + round(35 * scale) + 1)
    y0 = max(0, expected_y - round(50 * scale))
    y1 = min(height, expected_y + round(50 * scale) + 1)
    minimum_border_pixels = max(20, (x1 - x0) // 8)
    border_rows: list[tuple[int, int]] = []
    for y in range(y0, y1):
        gray_pixels = 0
        row = y * width * 4
        for x in range(x0, x1, 2):
            index = row + x * 4
            blue, green, red = pixels[index], pixels[index + 1], pixels[index + 2]
            if max(red, green, blue) - min(red, green, blue) <= 5 and 205 <= red <= 240:
                gray_pixels += 1
        if gray_pixels >= minimum_border_pixels:
            border_rows.append((y, gray_pixels))

    minimum_height = round(28 * scale)
    maximum_height = round(50 * scale)
    best: tuple[float, int] | None = None
    for top, top_score in border_rows:
        if top > expected_y:
            continue
        for bottom, bottom_score in border_rows:
            border_height = bottom - top
            if bottom < expected_y or not minimum_height <= border_height <= maximum_height:
                continue
            center = round((top + bottom) / 2)
            # Prefer a pair centered on the predicted row and close to the
            # reference input height (40 px before DPI scaling).
            score = (
                top_score
                + bottom_score
                - abs(center - expected_y) * 10
                - abs(border_height - 40 * scale) * 2
            )
            if best is None or score > best[0]:
                best = score, center
    return best[1] if best else None


def locate_control(hwnd: int, role: str, reference: tuple[int, int]) -> tuple[int, int]:
    width, _height = client_size(hwnd)
    expected_client = scaled_reference_point(width, reference)
    expected_screen = client_to_screen(hwnd, expected_client)
    accessible = choose_uia_control(
        enumerate_uia_controls(hwnd), role, expected_screen, client_screen_rect(hwnd)
    )
    label = CONTROL_LABELS.get(role, role)
    if accessible:
        log(f"定位 {label}：UI Automation")
        return accessible
    visual = visually_refine_blue_control(hwnd, role, expected_client)
    if visual:
        log(f"定位 {label}：窗口图像识别")
        return client_to_screen(hwnd, visual)
    log(f"定位 {label}：窗口比例自适应")
    return expected_screen


def click_screen(hwnd: int, point: tuple[int, int]) -> None:
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    x, y = point
    user32.SetCursorPos(x, y)
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.12)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.55)


def click(hwnd: int, point: tuple[int, int], role: str | None = None) -> None:
    target = locate_control(hwnd, role, point) if role else client_point(hwnd, point)
    click_screen(hwnd, target)


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
    click(hwnd, AE_PLATFORM_POINT, "ae_platform")
    time.sleep(3)


def keyboard(vk: int, up: bool = False) -> None:
    inp = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)))
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def replace_text(hwnd: int, point: tuple[int, int], text: str, role: str) -> None:
    target = locate_control(hwnd, role, point)
    click_screen(hwnd, target)
    # The embedded browser sometimes accepts the mouse click visually before
    # its input element has keyboard focus.  Waiting here prevents the first
    # digit from being swallowed.
    time.sleep(0.8)
    # A second click is intentional: the first can merely activate the
    # Chromium-based child surface after the receiver wait returns.
    click_screen(hwnd, target)
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
    replace_text(hwnd, PHONE_POINT, phone, "phone")
    requested_after = datetime.now(timezone.utc)
    log("请求短信验证码")
    click(hwnd, REQUEST_POINT, "request")
    log(f"等待手机转发新验证码（最长 {timeout} 秒）")
    code = wait_for_code(token, requested_after, timeout, sender)
    log("已收到验证码，正在填写并登录")
    hwnd = find_window()
    if not hwnd:
        raise RuntimeError("等待验证码期间 aTrust 登录窗口已关闭")
    replace_text(hwnd, CODE_POINT, code, "code")
    click(hwnd, LOGIN_POINT, "login")
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
