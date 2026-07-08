from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .service import continue_onboarding, get_onboarding_status, start_onboarding

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardingStartRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Engineer name")
    role: str = Field("engineer", description="Role: engineer, designer, marketer, etc.")


class OnboardingContinueRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Engineer name")
    message: str = Field(..., min_length=1, max_length=5000, description="Engineer's response")
    current_step: str = Field(..., description="Current onboarding step")


@router.post(
    "/start",
    summary="Start engineer onboarding conversation",
    description=(
        "Begin a structured onboarding conversation with a new engineer. The PM "
        "asks about their role, skills, past projects, availability, interests, "
        "and work style — one question at a time. Facts are extracted and stored "
        "automatically as the conversation progresses."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def start_onboarding_endpoint(
    payload: OnboardingStartRequest, org: Organization = Depends(get_current_org)
):
    result = await start_onboarding(org.graph_name, payload.name, payload.role)
    return result


@router.post(
    "/continue",
    summary="Continue engineer onboarding conversation",
    description=(
        "Continue the onboarding conversation. The engineer's response is ingested, "
        "facts are extracted, and the PM generates the next question or moves to "
        "the next step. The conversation progresses through: role_experience → "
        "skills → past_projects → availability → interests → work_style → done."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def continue_onboarding_endpoint(
    payload: OnboardingContinueRequest, org: Organization = Depends(get_current_org)
):
    result = await continue_onboarding(
        org.graph_name, payload.name, payload.message, payload.current_step
    )
    return result


@router.get(
    "/status",
    summary="Check onboarding progress",
    description=(
        "Check how far along an engineer is in the onboarding process. Returns "
        "the current step, whether it's completed, and what information has been "
        "collected so far."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def onboarding_status_endpoint(
    name: str = Query(..., min_length=1, max_length=200, description="Engineer name"),
    org: Organization = Depends(get_current_org),
):
    return await get_onboarding_status(org.graph_name, name)
