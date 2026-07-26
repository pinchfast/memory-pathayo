from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .service import (
    analyze_dependencies,
    detect_scope_creep,
    estimation_accuracy,
    prioritize_tasks,
)

router = APIRouter(prefix="/planning", tags=["planning"])


class ScopeCreepRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=200)


@router.post(
    "/scope-creep",
    summary="Detect scope creep for a project",
    description=(
        "Compare the original project scope (requirements from intake) against "
        "what has been added since. Flags specific additions that weren't in "
        "the original plan and assesses impact on timeline and capacity. "
        "Generates a plain-language message for the founder about scope changes."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def scope_creep_endpoint(
    payload: ScopeCreepRequest, org: Organization = Depends(get_current_org)
):
    store = await get_org_store(org.graph_name)
    return await detect_scope_creep(store, payload.project)


@router.get(
    "/dependencies",
    summary="Analyze task dependencies — chains, critical path, downstream risks",
    description=(
        "Analyze all blocker/dependency relationships in the project. Finds "
        "dependency chains, identifies the critical path (longest chain), and "
        "flags downstream risks where an overdue blocker is putting dependent "
        "work at risk."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def dependencies_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200, description="Filter by project"),
):
    store = await get_org_store(org.graph_name)
    return await analyze_dependencies(store, project)


@router.get(
    "/estimation-accuracy",
    summary="Track estimation accuracy per engineer",
    description=(
        "Compare estimated vs. actual completion time for done tasks. Computes "
        "per-person calibration: who underestimates, who overestimates, who is "
        "accurate. Returns the estimation ratio (actual / estimated) for each "
        "completed task."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def estimation_accuracy_endpoint(
    org: Organization = Depends(get_current_org),
    person: str | None = Query(None, max_length=200, description="Filter by person"),
):
    store = await get_org_store(org.graph_name)
    return await estimation_accuracy(store, person)


@router.get(
    "/prioritize",
    summary="Prioritize open tasks — business value × urgency × dependencies",
    description=(
        "Rank all open tasks by a composite priority score: deadline urgency "
        "(overdue tasks first), dependency order (blocking tasks first), "
        "critical path membership, and quick-win factor. Returns a recommended "
        "execution order."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def prioritize_endpoint(
    org: Organization = Depends(get_current_org),
    project: str | None = Query(None, max_length=200, description="Filter by project"),
):
    store = await get_org_store(org.graph_name)
    return await prioritize_tasks(store, project)
