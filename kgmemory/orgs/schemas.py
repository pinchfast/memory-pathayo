from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    preferred_language: str = Field("en", max_length=16)
    slack_team_id: str | None = Field(None, max_length=64)
    webhook_url: str | None = Field(None, max_length=500, description="Webhook URL for push-based alert delivery")
    webhook_secret: str | None = Field(None, max_length=128, description="Secret for webhook HMAC signature verification")
    report_schedule: str = Field("none", max_length=16, description="Report frequency: none, daily, weekly")
    report_email: str | None = Field(None, max_length=255, description="Email to send scheduled reports to")


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    preferred_language: str
    slack_team_id: str | None
    webhook_url: str | None
    report_schedule: str
    report_email: str | None
    created_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    webhook_url: str | None = None
    webhook_secret: str | None = None
    report_schedule: str | None = Field(None, pattern=r"^(none|daily|weekly)$")
    report_email: str | None = None
    preferred_language: str | None = Field(None, max_length=16)


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class APIKeyRead(BaseModel):
    id: UUID
    name: str
    prefix: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


class APIKeyCreated(APIKeyRead):
    key: str
