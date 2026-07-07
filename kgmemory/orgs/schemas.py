from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    preferred_language: str = Field("en", max_length=16)
    slack_team_id: str | None = Field(None, max_length=64)


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    preferred_language: str
    slack_team_id: str | None
    created_at: datetime


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
