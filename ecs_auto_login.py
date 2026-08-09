from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "ecs_login_config.json"
SESSION_FILE = ROOT / "ecs_session_cookies.txt"
RECEIVER_CONFIG = Path(os.environ.get("LOCALAPPDATA", "")) / "SmsUsbForwarder" / "config.json"
API_URL = "http://127.0.0.1:8765"
SERVICE_URL = "https://ecs.snerdi.com.cn/ecs/"
LOGIN_URL = "https://cas.snerdi.com.cn/cas/login?service=" + urllib.parse.quote(SERVICE_URL, safe="")
VERIFY_URL = "https://cas.snerdi.com.cn/cas/casLoginGetVerifyCode.jsp"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDM9aqcha+aSbl2tdzME2H3
UnXbv0KeGZwwrWDHJpeFBj313RgYfRX7jlsGciqUzTxC/3Qp+1ttzfUSZRwM
JEm536c9ARXIOzJF23hQ9ta8uZj3xffKqHEW95KOlLkSU7jPjkzruRZ5hbVh
CV4zTZfZwo3tOe9h0SaK6uoWIYU6sQIDAQAB
-----END PUBLIC KEY-----"""


class HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        data = dict(attrs)
        key = data.get("id") or data.get("name")
        if key:
            self.values[key] = data.get("value") or ""


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def decode_response(response, data: bytes) -> str:
    charset = response.headers.get_content_charset() or "utf-8"
    try:
        return data.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise RuntimeError(f"找不到配置文件: {CONFIG_FILE}")
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    for key in ("username", "password"):
        value = str(config.get(key, "")).strip()
        if not value or value.startswith("在这里填写"):
            raise RuntimeError(f"请在 ecs_login_config.json 中填写 {key}")
    timeout = int(config.get("smsTimeoutSeconds", 120))
    if not 1 <= timeout <= 300:
        raise RuntimeError("smsTimeoutSeconds 必须在 1 到 300 之间")
    config["username"] = str(config["username"]).strip().upper()
    config["password"] = str(config["password"])
    config["smsTimeoutSeconds"] = timeout
    password_encoding = str(config.get("verificationPasswordEncoding", "url")).lower()
    if password_encoding not in {"url", "raw"}:
        raise RuntimeError("verificationPasswordEncoding 只能是 url 或 raw")
    config["verificationPasswordEncoding"] = password_encoding
    return config


def receiver_token() -> str:
    if not RECEIVER_CONFIG.exists():
        raise RuntimeError(f"找不到短信接收器配置: {RECEIVER_CONFIG}")
    token = json.loads(RECEIVER_CONFIG.read_text(encoding="utf-8")).get("apiToken")
    if not token:
        raise RuntimeError("短信接收器配置中没有 apiToken")
    return str(token)


def rsa_encrypt(value: str) -> str:
    cipher = PKCS1_v1_5.new(RSA.import_key(PUBLIC_KEY))
    encrypted = cipher.encrypt(value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def wait_for_code(token: str, after: datetime, timeout: int, sender: str | None) -> str:
    body = json.dumps(
        {"timeoutSeconds": timeout, "senderContains": sender or None, "after": after.isoformat()}
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL + "/api/wait-code",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout + 10) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 408:
            raise TimeoutError(f"{timeout} 秒内未收到 AE 平台的新验证码") from exc
        raise RuntimeError(f"短信接收接口返回 HTTP {exc.code}") from exc
    code = str(result.get("code", ""))
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError("短信接收接口返回的 AE 验证码不是 6 位数字")
    return code


def build_opener(direct: bool = False) -> tuple[urllib.request.OpenerDirector, http.cookiejar.MozillaCookieJar]:
    cookies = http.cookiejar.MozillaCookieJar(str(SESSION_FILE))
    handlers: list[object] = [urllib.request.HTTPCookieProcessor(cookies)]
    if direct:
        handlers.insert(0, urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Language", "zh-CN,zh;q=0.9")]
    return opener, cookies


def fetch_login_page(opener: urllib.request.OpenerDirector) -> dict[str, str]:
    with opener.open(LOGIN_URL, timeout=8) as response:
        html = decode_response(response, response.read())
    parser = HiddenInputParser()
    parser.feed(html)
    lt = parser.values.get("lt")
    salt = parser.values.get("huoquyincangshuxing")
    if not lt or not salt:
        raise RuntimeError("CAS 登录页缺少 lt 或隐藏盐值")
    return {"lt": lt, "salt": salt}


def open_login_session(
    timeout: int = 90,
) -> tuple[urllib.request.OpenerDirector, http.cookiejar.MozillaCookieJar, dict[str, str]]:
    # This PC has a local browser proxy. Depending on its current routing
    # rules, the aTrust-only hostname may work through that proxy or directly.
    # Alternate both routes and retain the first complete Cookie session.
    sessions = [build_opener(direct=False), build_opener(direct=True)]
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        for opener, cookies in sessions:
            try:
                return opener, cookies, fetch_login_page(opener)
            except Exception as exc:
                last_error = exc
            if time.monotonic() >= deadline:
                break
        time.sleep(1)
    raise TimeoutError(f"aTrust 登录后 {timeout} 秒内仍无法访问 CAS: {last_error}")


def javascript_encode_uri_component(value: str) -> str:
    return urllib.parse.quote(value, safe="~()*!.'-", encoding="utf-8", errors="strict")


def send_verification_code(
    opener: urllib.request.OpenerDirector,
    username: str,
    password: str,
    password_encoding: str,
) -> str:
    verification_password = (
        javascript_encode_uri_component(password) if password_encoding == "url" else password
    )
    query = urllib.parse.urlencode(
        {"type": "send", "u": rsa_encrypt(username), "p": rsa_encrypt(verification_password)}
    )
    request = urllib.request.Request(
        VERIFY_URL + "?" + query,
        headers={"Referer": LOGIN_URL, "X-Requested-With": "XMLHttpRequest", "Accept": "*/*"},
    )
    with opener.open(request, timeout=30) as response:
        result = decode_response(response, response.read()).strip()
    compact = " ".join(result.split())
    if "success" not in compact.lower():
        raise RuntimeError(f"CAS 拒绝发送验证码: {compact[:300]}")
    return compact


def submit_login(
    opener: urllib.request.OpenerDirector,
    username: str,
    password: str,
    code: str,
    hidden: dict[str, str],
) -> tuple[str, str]:
    form = urllib.parse.urlencode(
        {
            "username2": username,
            "username": f"{username};{hidden['salt']};{code}",
            "password": rsa_encrypt(password),
            "verifyCode": code,
            "lt": hidden["lt"],
            "_eventId": "submit",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        LOGIN_URL,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://cas.snerdi.com.cn",
            "Referer": LOGIN_URL,
        },
        method="POST",
    )
    with opener.open(request, timeout=60) as response:
        final_url = response.geturl()
        html = decode_response(response, response.read())
    if not final_url.lower().startswith(SERVICE_URL.lower()):
        parser = HiddenInputParser()
        parser.feed(html)
        raise RuntimeError("CAS 登录失败，未获得 ECS service ticket；请检查账号、密码或验证码")
    return final_url, html


def run() -> None:
    config = load_config()
    token = receiver_token()
    log("等待 aTrust 隧道可访问 CAS 登录页")
    opener, cookies, hidden = open_login_session()
    requested_after = datetime.now(timezone.utc)
    log("通过 CAS 接口请求 AE 平台短信验证码")
    result = send_verification_code(
        opener,
        config["username"],
        config["password"],
        config["verificationPasswordEncoding"],
    )
    log(result)
    code = wait_for_code(
        token,
        requested_after,
        config["smsTimeoutSeconds"],
        str(config.get("smsSenderContains", "")).strip() or None,
    )
    log("提交 CAS 加密登录请求")
    final_url, _html = submit_login(opener, config["username"], config["password"], code, hidden)
    cookies.save(ignore_discard=True, ignore_expires=True)
    log(f"AE 协调平台登录成功: {final_url}")
    log(f"会话 Cookie 已保存到: {SESSION_FILE}")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n已停止", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
