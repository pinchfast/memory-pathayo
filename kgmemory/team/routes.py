from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .service import generate_performance_feedback, sense_team_morale

router = APIRouter(prefix="/team", tags=["team"])


class FeedbackRequest(BaseModel):
    engineer: str = Field(..., min_length=1, max_length=200, description="Engineer name")


@router.post(
    "/performance-feedback",
    summary="Generate honest performance feedback for an engineer",
    description=(
        "Generate honest, specific performance feedback based on contribution "
        "data, reliability score, fulfilled vs. missed commitments, and recent "
        "work reviews. References specific work, not generic praise. Suggests "
        "one concrete area for growth."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def performance_feedback_endpoint(
    payload: FeedbackRequest, org: Organization = Depends(get_current_org)
):
    result = await generate_performance_feedback(org.graph_name, payload.engineer)
    if "error" in result:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result


@router.post(
    "/morale",
    summary="Sense team morale from conversation patterns",
    description=(
        "Analyze sentiment trends across the team for the last 14 days. "
        "Detects declining morale from frustrated language, increased blockers, "
        "complaints, and silence patterns. Returns a team morale score and "
        "recommended actions if morale is dropping."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def morale_endpoint(org: Organization = Depends(get_current_org)):
    return await sense_team_morale(org.graph_name)
