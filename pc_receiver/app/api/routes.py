from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from threading import Event

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.models.messages import CodeResponse, HealthResponse, WaitCodeRequest
from app.storage.latest_code import LatestCodeStore


def create_router(settings: Settings, store: LatestCodeStore, usb_service) -> APIRouter:
    router = APIRouter()
    dashboard_file = Path(__file__).resolve().parent.parent / "web" / "dashboard.html"
    dashboard_session = secrets.token_urlsafe(32)

    def authorize(authorization: str | None = Header(default=None), smsusb_session: str | None = Cookie(default=None)) -> None:
        prefix = "Bearer "
        bearer_valid = authorization is not None and authorization.startswith(prefix) and secrets.compare_digest(authorization[len(prefix):], settings.api_token)
        session_valid = smsusb_session is not None and secrets.compare_digest(smsusb_session, dashboard_session)
        if not bearer_valid and not session_valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> HTMLResponse:
        response = HTMLResponse(
            dashboard_file.read_text(encoding="utf-8"),
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            },
        )
        response.set_cookie("smsusb_session", dashboard_session, max_age=8 * 60 * 60, httponly=True, samesite="strict", path="/")
        return response

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(usbConnected=usb_service.connected, lastMessageAt=usb_service.last_message_at)

    @router.get("/api/latest-code", response_model=CodeResponse, dependencies=[Depends(authorize)])
    def latest_code(consume: bool = Query(default=False)) -> CodeResponse:
        current = store.get(consume=consume)
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no unexpired code")
        return current.response()

    @router.post("/api/wait-code", response_model=CodeResponse, dependencies=[Depends(authorize)])
    async def wait_code(body: WaitCodeRequest, request: Request) -> CodeResponse:
        cancelled = Event()
        task = asyncio.create_task(asyncio.to_thread(store.wait, body.timeoutSeconds, body.senderContains, body.after, True, cancelled))
        try:
            current = await task
        except asyncio.CancelledError:
            cancelled.set()
            raise
        if current is None:
            raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="timed out waiting for a new matching code")
        return current.response()

    return router
