from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SmsCodeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocolVersion: Literal[1]
    messageId: UUID
    type: Literal["sms_code"]
    sender: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=4, max_length=32)
    smsTextMasked: str = Field(max_length=256)
    receivedAt: datetime
    sentAt: datetime
    nonce: str = Field(min_length=16, max_length=256)
    hmac: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("receivedAt", "sentAt")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone")
        return value


class AckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocolVersion: Literal[1] = 1
    type: Literal["ack"] = "ack"
    messageId: UUID
    status: Literal["accepted"] = "accepted"
    receivedAt: datetime


class CodeResponse(BaseModel):
    code: str
    sender: str
    receivedAt: datetime
    expiresAt: datetime


class WaitCodeRequest(BaseModel):
    timeoutSeconds: int = Field(default=120, ge=1, le=300)
    senderContains: str | None = Field(default=None, max_length=64)
    after: datetime | None = None

    @field_validator("after")
    @classmethod
    def after_timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("after must include timezone")
        return value


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    usbConnected: bool
    lastMessageAt: datetime | None
