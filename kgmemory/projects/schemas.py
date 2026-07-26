from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    status: Literal["planning", "active", "on_hold", "completed", "cancelled"] = "planning"
    deadline: str | None = None


class ProjectRead(BaseModel):
    name: str
    description: str | None
    status: str
    deadline: str | None
    task_count: int
    open_task_count: int
    member_count: int


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(None, max_length=2000)
    project: str = Field(min_length=1, max_length=200)
    required_skills: list[str] = Field(default_factory=list, max_length=20)
    estimated_days: float | None = None
    deadline: str | None = None


class TaskRead(BaseModel):
    task_id: str
    title: str | None = None
    project: str
    status: str
    required_skills: list[str]
    estimated_days: float | None
    deadline: str | None
    assignee: str | None


class AssignmentRecommendation(BaseModel):
    task: TaskRead
    recommendations: list[dict]
