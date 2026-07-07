from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    report_type: Literal["weekly", "status", "risk", "founder_summary"] = "weekly"
    language: str = Field("en", max_length=16)
    project: str | None = Field(None, max_length=200)


class ReportAccepted(BaseModel):
    report_id: str
    status: str = "queued"


class ReportStatus(BaseModel):
    report_id: str
    status: str
    report: dict | None = None
    error: str | None = None


class ReportRead(BaseModel):
    report_id: str
    report_type: str
    language: str
    title: str
    body_markdown: str
    highlights: list[str]
    risk_level: str
    created_at: datetime
