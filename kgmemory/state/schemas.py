from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProjectStateSnapshot(BaseModel):
    project: str
    health: Literal["on_track", "at_risk", "delayed", "blocked", "completed", "unknown"] = "unknown"
    health_score: float = Field(0.5, ge=0.0, le=1.0)
    open_commitments: int = 0
    completed_since_last: int = 0
    missed_or_late: int = 0
    open_blockers: int = 0
    active_engineers: int = 0
    last_activity: str | None = None
    risk_signals: list[str] = Field(default_factory=list)
    summary: str = ""
    inferred_at: datetime = Field(default_factory=lambda: datetime.now(datetime.timezone.utc))


class PersonStateSnapshot(BaseModel):
    person: str
    credibility: Literal["high", "moderate", "low", "unknown"] = "unknown"
    credibility_score: float = Field(0.5, ge=0.0, le=1.0)
    open_commitments: int = 0
    completed_since_last: int = 0
    missed_or_late: int = 0
    last_seen: str | None = None
    days_since_last_seen: int | None = None
    risk_signals: list[str] = Field(default_factory=list)
    summary: str = ""
    inferred_at: datetime = Field(default_factory=lambda: datetime.now(datetime.timezone.utc))


class StateInferenceResult(BaseModel):
    projects: list[ProjectStateSnapshot]
    people: list[PersonStateSnapshot]
    inferred_at: datetime
    elapsed_ms: int


class DecisionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    audience: Literal["founder_non_technical", "founder_technical", "engineer", "internal"] = "founder_non_technical"
    project: str | None = Field(None, max_length=200)
    max_facts: int = Field(20, ge=1, le=100)
    rerank: bool = True


class DecisionResponse(BaseModel):
    query: str
    audience: str
    response_text: str
    reasoning: str
    suggested_actions: list[dict]
    risk_level: Literal["low", "medium", "high"]
    context_facts: list[dict]
    project_states: list[dict]
    person_states: list[dict]
    elapsed_ms: int
