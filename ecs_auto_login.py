from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import math
import os
import re
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
DOWNLOAD_DIR = ROOT / "downloads"
RECEIVER_CONFIG = Path(os.environ.get("LOCALAPPDATA", "")) / "SmsUsbForwarder" / "config.json"
API_URL = "http://127.0.0.1:8765"
SERVICE_URL = "https://ecs.snerdi.com.cn/ecs/"
LOGIN_URL = "https://cas.snerdi.com.cn/cas/login?service=" + urllib.parse.quote(SERVICE_URL, safe="")
VERIFY_URL = "https://cas.snerdi.com.cn/cas/casLoginGetVerifyCode.jsp"
EXCEL_EXPORT_URL = "https://ecs.snerdi.com.cn/ecs/servlet/ExcelExpServlet"
EXCEL_REFERER = (
    "https://ecs.snerdi.com.cn/ecs/baseview/webquery/ProjectQueryPlan_Query_lui.jsp"
    "?__planid=P_TZljhCgwj&wjlb=0"
    "&comreq_xmid=3ccd801367400c9d01674f23302f4b89"
    "&comreq_dwid=T_BLXMXX230920496"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDM9aqcha+aSbl2tdzME2H3
UnXbv0KeGZwwrWDHJpeFBj313RgYfRX7jlsGciqUzTxC/3Qp+1ttzfUSZRwM
JEm536c9ARXIOzJF23hQ9ta8uZj3xffKqHEW95KOlLkSU7jPjkzruRZ5hbVh
CV4zTZfZwo3tOe9h0SaK6uoWIYU6sQIDAQAB
-----END PUBLIC KEY-----"""

EXCEL_EXPORT_PARAMS = (
    ";key=__planid,val=P_TZljhCgwj"
    ";key=curr,val=ENU68435"
    ";key=wjmc,val="
    ";key=wjbh,val="
    ";key=wjbb,val="
    ";key=xmid,val=3ccd801367400c9d01674f23302f4b89"
    ";key=fqdw,val=T_BLXMXX230920496"
    ";key=WJSPZT,val="
    ";key=sffzj,val="
    ";key=cjsj1,val="
    ";key=cjsj2,val="
    ";key=fqr,val="
    ";key=shr,val="
    ";key=pzr,val="
    ";key=jz,val="
    ";key=sbmc,val="
    ";key=hth,val="
    ";key=qcshr,val="
    ";key=bbzt,val=NEWB"
    ";key=zbfbm,val="
    ";key=bk,val="
    ";key=zbfshr,val="
    ";key=yzshr,val="
    ";key=zzfbh,val="
    ";key=sfcgfb,val="
)


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
    password_encoding = str(config.get("verificationPasswordEncoding", "raw")).lower()
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
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{timeout} 秒内未收到 AE 平台的新验证码")
        wait_seconds = max(1, min(2, math.ceil(remaining)))
        body = json.dumps(
            {
                "timeoutSeconds": wait_seconds,
                "senderContains": sender or None,
                "after": after.isoformat(),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            API_URL + "/api/wait-code",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=wait_seconds + 2) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 408:
                continue
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
    # The legacy JSP is not equivalent under normal URL percent-encoding.
    # Its browser implementation concatenates the RSA Base64 values verbatim,
    # so preserve '+', '/', and '=' exactly as captured from the successful
    # request instead of using urllib.parse.urlencode here.
    encrypted_user = rsa_encrypt(username)
    encrypted_password = rsa_encrypt(verification_password)
    query = "type=send&u=" + encrypted_user + "&p=" + encrypted_password
    request = urllib.request.Request(
        VERIFY_URL + "?" + query,
        headers={
            "Referer": LOGIN_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
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


def export_filename(content_disposition: str | None) -> str:
    header = content_disposition or ""
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", header, flags=re.IGNORECASE)
    decoded = urllib.parse.unquote(match.group(1).strip()) if match else "未命名.xls"
    safe_name = Path(decoded).name.replace("\x00", "").strip() or "未命名.xls"
    stem = Path(safe_name).stem or "未命名"
    suffix = Path(safe_name).suffix or ".xls"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{timestamp}{suffix}"


def download_excel(opener: urllib.request.OpenerDirector) -> Path:
    form = urllib.parse.urlencode(
        {
            "__expparams": EXCEL_EXPORT_PARAMS,
            "__expHander": "com.pucheit.service.query.ExcelQueryService",
            "__expMaxCount": "5000",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        EXCEL_EXPORT_URL,
        data=form,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://ecs.snerdi.com.cn",
            "Referer": EXCEL_REFERER,
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "x-uctiming-46938875": str(int(time.time() * 1000)),
        },
        method="POST",
    )
    log(f"请求导出 Excel（POST 表单 {len(form)} 字节）")
    with opener.open(request, timeout=120) as response:
        payload = response.read()
        disposition = response.headers.get("Content-Disposition")
        content_type = response.headers.get("Content-Type", "")
        status = response.status
    if status != 200:
        raise RuntimeError(f"Excel 导出接口返回 HTTP {status}")
    if not payload:
        raise RuntimeError("Excel 导出接口返回了空文件")
    if "attachment" not in (disposition or "").lower():
        preview = payload[:300].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Excel 导出响应不是附件，Content-Type={content_type!r}，响应开头={preview!r}"
        )
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output = DOWNLOAD_DIR / export_filename(disposition)
    output.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    log(f"Excel 下载成功: {output}")
    log(f"Excel 文件大小: {len(payload)} 字节，SHA-256: {checksum}")
    return output


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
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookies)
    log(f"当前登录 Cookie: {cookie_header or '<无 Cookie>'}")
    log(f"会话 Cookie 已保存到: {SESSION_FILE}")
    download_excel(opener)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n已停止", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
