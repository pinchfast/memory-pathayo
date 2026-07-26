from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .service import (
    generate_stakeholder_update,
    get_budget_status,
    record_spend,
    set_budget,
)

router = APIRouter(prefix="/stakeholders", tags=["stakeholders"])


class StakeholderUpdateRequest(BaseModel):
    stakeholder_type: str = Field(
        ...,
        description="Audience: investor, customer, team, or board",
        pattern=r"^(investor|customer|team|board)$",
    )
    project: str | None = Field(None, max_length=200, description="Filter to a specific project")


class BudgetSetRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)
    total_budget: float = Field(..., gt=0, description="Total budget amount")
    currency: str = Field("USD", max_length=10)
    start_date: str | None = Field(None, description="ISO date when budget period starts")
    end_date: str | None = Field(None, description="ISO date when budget period ends")


class SpendRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., gt=0, description="Amount spent")
    category: str = Field("general", max_length=100, description="Spend category: engineering, infrastructure, tools, etc.")
    description: str | None = Field(None, max_length=500)


@router.post(
    "/update",
    summary="Generate tailored update for a stakeholder",
    description=(
        "Generate an update tailored to a specific audience: investor (focus on "
        "milestones, burn rate, risks to investment), customer (delivery timelines, "
        "feature availability), team (what's next, priorities), or board (concise, "
        "data-driven, strategic risks)."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def stakeholder_update_endpoint(
    payload: StakeholderUpdateRequest, org: Organization = Depends(get_current_org)
):
    return await generate_stakeholder_update(org.graph_name, payload.stakeholder_type, payload.project)


@router.post(
    "/budget",
    summary="Set project budget",
    description="Set the total budget for a project, including currency and optional date range.",
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def set_budget_endpoint(
    payload: BudgetSetRequest, org: Organization = Depends(get_current_org)
):
    store = await get_org_store(org.graph_name)
    return await set_budget(
        store, payload.project, payload.total_budget, payload.currency,
        payload.start_date, payload.end_date,
    )


@router.post(
    "/budget/spend",
    summary="Record a spend against project budget",
    description="Record an expense against a project's budget. Categories: engineering, infrastructure, tools, marketing, etc.",
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def record_spend_endpoint(
    payload: SpendRequest, org: Organization = Depends(get_current_org)
):
    store = await get_org_store(org.graph_name)
    return await record_spend(store, payload.project, payload.amount, payload.category, payload.description)


@router.get(
    "/budget",
    summary="Get budget status — spent, remaining, utilization, runway",
    description=(
        "Get the current budget status for a project. Shows total budget, "
        "amount spent, remaining, utilization percentage, runway in weeks, "
        "spend by category, and a warning level (healthy / halfway / warning / critical)."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def budget_status_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200, description="Project name (omit for all projects)"),
):
    store = await get_org_store(org.graph_name)
    return await get_budget_status(store, project)
