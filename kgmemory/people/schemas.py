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
    experience_years: float | None = Field(None, description="Years of professional experience")
    availability_hours_per_week: float | None = Field(None, description="Available hours per week")
    timezone: str | None = Field(None, max_length=100, description="Timezone, e.g. 'UTC-5'")
    interests: list[str] = Field(default_factory=list, max_length=20, description="Areas of interest")
    career_goals: str | None = Field(None, max_length=1000, description="Career aspirations")
    resume_summary: str | None = Field(None, max_length=2000, description="Brief resume summary")


class PersonRead(BaseModel):
    name: str
    role: str
    title: str | None
    skills: list[str]
    languages: list[str]
    is_technical: bool
    experience_years: float | None = None
    availability_hours_per_week: float | None = None
    timezone: str | None = None
    interests: list[str] = Field(default_factory=list)
    career_goals: str | None = None
    resume_summary: str | None = None
    facts: list[dict] = Field(default_factory=list)
    reliability: dict = Field(default_factory=dict)
    contributions: dict = Field(default_factory=dict)


class PersonSummary(BaseModel):
    name: str
    role: str
    title: str | None
    skill_count: int
    commitment_count: int
    completed_count: int
    missed_count: int
    reliability_score: float
    availability_hours_per_week: float | None = None
    is_available: bool = True
