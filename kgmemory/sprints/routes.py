from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .service import (
    capacity_forecast,
    create_milestone,
    create_sprint,
    get_roadmap,
    get_sprint,
    list_milestones,
    list_sprints,
    plan_sprint,
    review_sprint,
)

router = APIRouter(prefix="/sprints", tags=["sprints"])


class SprintCreateRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1, max_length=500)
    sprint_days: int = Field(14, ge=1, le=42)
    start_date: str | None = Field(None, description="ISO date, defaults to now")


class MilestoneCreateRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=300)
    target_date: str = Field(..., description="ISO date")
    description: str | None = Field(None, max_length=2000)


@router.post("/create", summary="Create a new sprint", responses=ORG_PROTECTED_RESPONSES,
             openapi_extra={"security": [{"OrgAPIKey": []}]})
async def create_sprint_endpoint(payload: SprintCreateRequest, org: Organization = Depends(get_current_org)):
    store = await get_org_store(org.graph_name)
    return await create_sprint(store, payload.project, payload.goal, payload.sprint_days, payload.start_date)


# Static routes must come before /{sprint_id} to avoid being caught by it

# Milestones

@router.post("/milestones", summary="Create a milestone", responses=ORG_PROTECTED_RESPONSES,
             openapi_extra={"security": [{"OrgAPIKey": []}]})
async def create_milestone_endpoint(payload: MilestoneCreateRequest, org: Organization = Depends(get_current_org)):
    store = await get_org_store(org.graph_name)
    return await create_milestone(store, payload.project, payload.title, payload.target_date, payload.description)


@router.get("/milestones", summary="List milestones with progress", responses=ORG_PROTECTED_RESPONSES,
             openapi_extra={"security": [{"OrgAPIKey": []}]})
async def list_milestones_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200),
):
    store = await get_org_store(org.graph_name)
    return await list_milestones(store, project)


@router.get("/roadmap", summary="Get project roadmap — milestones and sprints in chronological order",
             responses=ORG_PROTECTED_RESPONSES, openapi_extra={"security": [{"OrgAPIKey": []}]})
async def roadmap_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200),
):
    store = await get_org_store(org.graph_name)
    return await get_roadmap(store, project)


# Capacity

@router.get("/capacity", summary="Capacity forecast — upcoming work vs available hours",
             description="Forecasts team capacity against upcoming work. Warns if overcommitted and suggests what to defer.",
             responses=ORG_PROTECTED_RESPONSES, openapi_extra={"security": [{"OrgAPIKey": []}]})
async def capacity_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200),
    weeks: int = Query(2, ge=1, le=12),
):
    store = await get_org_store(org.graph_name)
    return await capacity_forecast(store, project, weeks)


# Dynamic routes (must come after static routes)

@router.get("/", summary="List sprints", responses=ORG_PROTECTED_RESPONSES,
             openapi_extra={"security": [{"OrgAPIKey": []}]})
async def list_sprints_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200),
):
    store = await get_org_store(org.graph_name)
    return await list_sprints(store, project)


@router.post("/{sprint_id}/plan", summary="AI plans sprint tasks based on capacity",
             description="The PM analyzes team capacity, task dependencies, and priorities to select tasks for this sprint.",
             responses=ORG_PROTECTED_RESPONSES, openapi_extra={"security": [{"OrgAPIKey": []}]})
async def plan_sprint_endpoint(sprint_id: str, org: Organization = Depends(get_current_org)):
    store = await get_org_store(org.graph_name)
    result = await plan_sprint(store, sprint_id)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result


@router.get("/{sprint_id}", summary="Get sprint details with tasks",
             responses=ORG_PROTECTED_RESPONSES, openapi_extra={"security": [{"OrgAPIKey": []}]})
async def get_sprint_endpoint(sprint_id: str, org: Organization = Depends(get_current_org)):
    store = await get_org_store(org.graph_name)
    sprint = await get_sprint(store, sprint_id)
    if sprint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint


@router.post("/{sprint_id}/retrospective", summary="Run sprint retrospective",
             description="The PM analyzes what went well, what didn't, and generates lessons learned.",
             responses=ORG_PROTECTED_RESPONSES, openapi_extra={"security": [{"OrgAPIKey": []}]})
async def retrospective_endpoint(sprint_id: str, org: Organization = Depends(get_current_org)):
    store = await get_org_store(org.graph_name)
    result = await review_sprint(store, sprint_id)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result
