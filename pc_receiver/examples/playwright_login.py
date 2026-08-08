from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from playwright.async_api import async_playwright


API_URL = "http://127.0.0.1:8765"


def wait_for_code(token: str, after: datetime, timeout: int = 120) -> str:
    body = json.dumps({"timeoutSeconds": timeout, "senderContains": "1069", "after": after.isoformat()}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/api/wait-code",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout + 5) as response:
            return json.load(response)["code"]
    except urllib.error.HTTPError as exc:
        if exc.code == 408:
            raise TimeoutError(f"No new verification code arrived within {timeout} seconds") from exc
        raise RuntimeError(f"Local receiver API returned HTTP {exc.code}") from exc


async def main() -> None:
    token = os.environ.get("SMSUSB_API_TOKEN")
    target_url = os.environ.get("LOGIN_URL", "https://internal.example.invalid/login")
    if not token:
        raise RuntimeError("Set SMSUSB_API_TOKEN to the token shown by: python -m app.main show-config")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(target_url)
        requested_after = datetime.now(timezone.utc)
        await page.locator("#request-code").click()
        code = await asyncio.to_thread(wait_for_code, token, requested_after, 120)
        await page.locator("#verification-code").fill(code)
        await page.locator("#login-button").click()
        try:
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception as exc:
            raise RuntimeError("Login did not reach a settled result within 30 seconds") from exc
        print("Login action completed; verify the resulting page using an internal-system-specific assertion.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
