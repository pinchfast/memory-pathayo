from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: Literal["founder", "engineer", "marketer", "manager", "designer", "other"] = "other"
    title: str | None = Field(None, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=50)
    languages: list[str] = Field(default_factory=list, max_length=10)
    is_technical: bool = False


class PersonRead(BaseModel):
    name: str
    role: str
    title: str | None
    skills: list[str]
    languages: list[str]
    is_technical: bool
    facts: list[dict] = Field(default_factory=list)
    reliability: dict = Field(default_factory=dict)


class PersonSummary(BaseModel):
    name: str
    role: str
    title: str | None
    skill_count: int
    commitment_count: int
    completed_count: int
    missed_count: int
    reliability_score: float
