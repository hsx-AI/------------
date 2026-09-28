r"""独立调试：仅请求 AE/CAS 发送短信验证码，不提交最终登录。

运行方式（必须使用 pc_receiver 虚拟环境，其中已安装 pycryptodome）：
    .\pc_receiver\.venv\Scripts\python.exe .\ae_sms_debug.py
"""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


# ======================== 请在这里填写 ========================
USERNAME = "AU158842"
PASSWORD = "Hsx@19980212"

# 根据你提供的 style_vc.js，实际执行加密的是：
#     setrea($('#password').val())
# 因此建议先使用 raw。只有 raw 明确失败后，再手工改成 url 单独测试。
PASSWORD_ENCODING = "raw"  # 只能填写 "raw" 或 "url"

# generated：使用本程序根据上面的账号密码生成 RSA 密文。
# captured：使用你从浏览器成功请求中复制的 u/p 密文，用于对照诊断。
CIPHERTEXT_MODE = "generated"  # generated / captured
CAPTURED_U = ""
CAPTURED_P = ""

# browser_raw 精确复刻浏览器 cURL，直接把 Base64 拼入 URL；
# percent 使用标准百分号编码。建议先测试 browser_raw。
QUERY_SERIALIZATION = "browser_raw"  # browser_raw / percent

# auto 会先使用 Windows/环境代理，再尝试完全直连。
# 也可固定填写 "proxy" 或 "direct"。
NETWORK_MODE = "auto"  # auto / proxy / direct
REQUEST_TIMEOUT_SECONDS = 20
# =============================================================


SERVICE_URL = "https://ecs.snerdi.com.cn/ecs/"
LOGIN_URL = "https://cas.snerdi.com.cn/cas/login?service=" + urllib.parse.quote(
    SERVICE_URL, safe=""
)
VERIFY_URL = "https://cas.snerdi.com.cn/cas/casLoginGetVerifyCode.jsp"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDM9aqcha+aSbl2tdzME2H3
UnXbv0KeGZwwrWDHJpeFBj313RgYfRX7jlsGciqUzTxC/3Qp+1ttzfUSZRwM
JEm536c9ARXIOzJF23hQ9ta8uZj3xffKqHEW95KOlLkSU7jPjkzruRZ5hbVh
CV4zTZfZwo3tOe9h0SaK6uoWIYU6sQIDAQAB
-----END PUBLIC KEY-----"""


class InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = dict(attrs)
        key = values.get("id") or values.get("name")
        if key:
            self.inputs[key] = values.get("value") or ""


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def masked(value: str, keep: int = 3) -> str:
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "…" + value[-keep:]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def decode_response(response, payload: bytes) -> str:
    declared = response.headers.get_content_charset()
    for encoding in filter(None, (declared, "utf-8", "gb18030")):
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    return payload.decode("utf-8", errors="replace")


def javascript_encode_uri_component(value: str) -> str:
    return urllib.parse.quote(value, safe="~()*!.'-", encoding="utf-8", errors="strict")


def rsa_encrypt(value: str) -> str:
    key = RSA.import_key(PUBLIC_KEY)
    cipher = PKCS1_v1_5.new(key)
    return base64.b64encode(cipher.encrypt(value.encode("utf-8"))).decode("ascii")


def build_session(direct: bool):
    jar = http.cookiejar.CookieJar()
    handlers: list[object] = [urllib.request.HTTPCookieProcessor(jar)]
    if direct:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept-Language", "zh-CN,zh;q=0.9"),
    ]
    return opener, jar


def cookie_summary(jar: http.cookiejar.CookieJar) -> str:
    values = []
    for cookie in jar:
        values.append(
            f"{cookie.domain}{cookie.path} {cookie.name}={masked(cookie.value, 4)} "
            f"secure={cookie.secure}"
        )
    return "; ".join(values) if values else "<无 Cookie>"


def open_login_page(opener, jar, route_name: str) -> tuple[str, str]:
    log(f"[{route_name}] GET 登录页")
    started = time.monotonic()
    request = urllib.request.Request(
        LOGIN_URL,
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = response.read()
        html = decode_response(response, payload)
        log(
            f"[{route_name}] 登录页 HTTP {response.status}，最终 URL={response.geturl()}，"
            f"响应 {len(payload)} 字节，耗时 {time.monotonic() - started:.2f}s"
        )
        log(f"[{route_name}] Content-Type={response.headers.get('Content-Type')!r}")
    log(f"[{route_name}] Cookie：{cookie_summary(jar)}")

    parser = InputParser()
    parser.feed(html)
    lt = parser.inputs.get("lt", "")
    salt = parser.inputs.get("huoquyincangshuxing", "")
    log(
        f"[{route_name}] 页面字段：input 数量={len(parser.inputs)}，"
        f"lt 长度={len(lt)}，salt 长度={len(salt)}"
    )
    if not lt or not salt:
        title_start = html.lower().find("<title")
        title_end = html.lower().find("</title>")
        title_fragment = html[title_start : title_end + 8] if title_start >= 0 else "<没有 title>"
        raise RuntimeError(f"登录页缺少 lt/salt；页面标题片段：{title_fragment[:300]!r}")
    return lt, salt


def request_sms(opener, jar, route_name: str) -> str:
    username = USERNAME.strip().upper()
    password_for_verify = (
        PASSWORD if PASSWORD_ENCODING == "raw" else javascript_encode_uri_component(PASSWORD)
    )
    if CIPHERTEXT_MODE == "captured":
        encrypted_user = CAPTURED_U.strip()
        encrypted_password = CAPTURED_P.strip()
    else:
        encrypted_user = rsa_encrypt(username)
        encrypted_password = rsa_encrypt(password_for_verify)

    log(
        f"[{route_name}] 加密前元数据：username 长度={len(username)}，"
        f"password 长度={len(PASSWORD)}，处理后长度={len(password_for_verify)}，"
        f"密码模式={PASSWORD_ENCODING}，密文来源={CIPHERTEXT_MODE}，"
        f"查询串模式={QUERY_SERIALIZATION}"
    )
    log(
        f"[{route_name}] 明文摘要（用于比较配置是否变化，不可反推明文）："
        f"username sha256={digest(username)}，password sha256={digest(PASSWORD)}，"
        f"处理后 password sha256={digest(password_for_verify)}"
    )
    log(
        f"[{route_name}] RSA：账号密文长度={len(encrypted_user)}，sha256={digest(encrypted_user)}；"
        f"密码密文长度={len(encrypted_password)}，sha256={digest(encrypted_password)}"
    )

    if QUERY_SERIALIZATION == "browser_raw":
        query = "type=send&u=" + encrypted_user + "&p=" + encrypted_password
    else:
        query = urllib.parse.urlencode(
            {"type": "send", "u": encrypted_user, "p": encrypted_password}
        )
    safe_url = VERIFY_URL + "?type=send&u=<RSA-172-chars>&p=<RSA-172-chars>"
    log(f"[{route_name}] GET {safe_url}")
    request = urllib.request.Request(
        VERIFY_URL + "?" + query,
        headers={
            "Accept": "*/*",
            "Referer": LOGIN_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    started = time.monotonic()
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = response.read()
        text = decode_response(response, payload)
        log(
            f"[{route_name}] 验证码接口 HTTP {response.status}，响应 {len(payload)} 字节，"
            f"耗时 {time.monotonic() - started:.2f}s"
        )
        log(f"[{route_name}] 响应头 Content-Type={response.headers.get('Content-Type')!r}")
    log(f"[{route_name}] 请求后 Cookie：{cookie_summary(jar)}")
    log(f"[{route_name}] 服务器原始响应 repr={text!r}")
    return " ".join(text.split())


def validate_settings() -> None:
    if not USERNAME or USERNAME.startswith("在这里填写"):
        raise RuntimeError("请先在脚本顶部填写 USERNAME")
    if not PASSWORD or PASSWORD.startswith("在这里填写"):
        raise RuntimeError("请先在脚本顶部填写 PASSWORD")
    if PASSWORD_ENCODING not in {"raw", "url"}:
        raise RuntimeError('PASSWORD_ENCODING 只能填写 "raw" 或 "url"')
    if CIPHERTEXT_MODE not in {"generated", "captured"}:
        raise RuntimeError('CIPHERTEXT_MODE 只能填写 "generated" 或 "captured"')
    if CIPHERTEXT_MODE == "captured" and (not CAPTURED_U.strip() or not CAPTURED_P.strip()):
        raise RuntimeError("captured 模式必须填写 CAPTURED_U 和 CAPTURED_P")
    if QUERY_SERIALIZATION not in {"browser_raw", "percent"}:
        raise RuntimeError('QUERY_SERIALIZATION 只能填写 "browser_raw" 或 "percent"')
    if NETWORK_MODE not in {"auto", "proxy", "direct"}:
        raise RuntimeError('NETWORK_MODE 只能填写 "auto"、"proxy" 或 "direct"')


def main() -> int:
    validate_settings()
    log("AE 验证码独立调试程序启动；本程序不会提交最终登录")
    log(f"Python={sys.version.split()[0]}，主机={socket.gethostname()}")
    proxies = urllib.request.getproxies()
    safe_proxies = {key: value for key, value in proxies.items() if key in {"http", "https"}}
    log(f"系统检测到的 HTTP(S) 代理={safe_proxies or '<无>'}")

    routes = []
    if NETWORK_MODE in {"auto", "proxy"}:
        routes.append(("系统代理", False))
    if NETWORK_MODE in {"auto", "direct"}:
        routes.append(("完全直连", True))

    last_error: Exception | None = None
    for route_name, direct in routes:
        opener, jar = build_session(direct)
        try:
            open_login_page(opener, jar, route_name)
            result = request_sms(opener, jar, route_name)
            if "success" in result.lower():
                log(f"成功：{result}")
                return 0
            if "error" in result.lower():
                log(f"服务器明确拒绝：{result}")
                log("为避免账号锁定，本次不会自动尝试另一种密码编码模式。")
                return 2
            log(f"未知响应：{result}")
            return 3
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            log(f"[{route_name}] 网络失败：{type(exc).__name__}: {exc}")
            if NETWORK_MODE != "auto":
                break

    raise RuntimeError(f"所有网络路线均失败：{last_error}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n用户取消。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
