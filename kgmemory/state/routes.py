from fastapi import APIRouter, Depends, Query

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .checkin import check_in_auto, check_in_person
from .decision import decide
from .inference import infer_and_snapshot_state
from .schemas import DecisionRequest, DecisionResponse, StateInferenceResult

router = APIRouter(prefix="/pm", tags=["pm-brain"])

DECIDE_EXAMPLE = {
    "query": "Is the API project on track? Should I be worried?",
    "audience": "founder_non_technical",
    "rerank": True,
}
DECIDE_RESPONSE_EXAMPLE = {
    "query": "Is the API project on track?",
    "audience": "founder_non_technical",
    "response_text": (
        "The API project is running behind. Dave promised to ship the auth module "
        "by last Friday but hasn't delivered, and he's been quiet for 4 days. "
        "I'd recommend we check in with him today."
    ),
    "reasoning": (
        "Dave has 1 open commitment overdue by 3 days, 0 completions, and a 4-day "
        "silence. His credibility is moderate but trending down. The project has "
        "no other active engineers, making it a single point of failure."
    ),
    "suggested_actions": [
        {
            "action": "ping",
            "target": "dave",
            "message": "Hey Dave, any update on the auth module? It's past the Friday deadline.",
            "urgency": "high",
        },
        {
            "action": "warn_founder",
            "target": "api",
            "message": "API project is at risk — sole engineer is overdue and silent.",
            "urgency": "medium",
        },
    ],
    "risk_level": "high",
    "context_facts": [],
    "project_states": [],
    "person_states": [],
    "elapsed_ms": 2400,
}


@router.post(
    "/decide",
    response_model=DecisionResponse,
    summary="PM decision and response synthesis",
    description=(
        "The AI project manager's reasoning layer. Runs a full context search, "
        "injects current project and person states, then uses the PM_DECISION_PROMPT "
        "to synthesize an audience-tuned response with internal reasoning and "
        "concrete suggested actions (ping, escalate, reassign, warn_founder). "
        "**This is the endpoint the Django backend calls to generate the PM agent's "
        "reply to a founder or engineer.**"
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "Decision with response and actions",
            "content": {"application/json": {"example": DECIDE_RESPONSE_EXAMPLE}},
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def decide_endpoint(payload: DecisionRequest, org: Organization = Depends(get_current_org)):
    result = await decide(org.graph_name, payload)
    return DecisionResponse(**result)


@router.post(
    "/infer-state",
    response_model=StateInferenceResult,
    summary="Trigger state inference manually",
    description=(
        "Manually trigger project health and person credibility inference, storing "
        "durable snapshots in the graph. This normally runs automatically "
        "fire-and-forget after each ingest, but this endpoint lets you force a "
        "refresh (e.g. after bulk imports or time-based decay)."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def infer_state_endpoint(org: Organization = Depends(get_current_org)):
    result = await infer_and_snapshot_state(org.graph_name)
    return StateInferenceResult(**result)


CHECKIN_EXAMPLE = {
    "person": "dave",
    "needed": True,
    "reason": "has overdue commitments",
    "check_in_message": (
        "Hey Dave, I wanted to check in on the auth module — it was due last "
        "Friday and I haven't seen an update. Can you let me know where things "
        "stand by end of day today? Specifically: is the OAuth token refresh "
        "still blocking you, and do you need any help?"
    ),
    "tone": "friendly_concerned",
    "specific_questions": [
        "What's the current status of the auth module?",
        "Is the OAuth token refresh still blocking you?",
    ],
    "open_commitments": [
        {"value": "ship auth module", "due_date": "2026-07-04", "project": "api"}
    ],
    "days_since_last_seen": 4,
    "elapsed_ms": 1800,
}


@router.post(
    "/check-in",
    summary="Proactive check-in for a specific person",
    description=(
        "Generate a proactive check-in message for a specific team member. "
        "The PM references their actual open commitments, mentions overdue "
        "items if any, and asks for a concrete update with a response deadline. "
        "If no check-in is needed (person is active and on track), returns "
        "`needed: false`."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "Check-in message generated",
            "content": {"application/json": {"example": CHECKIN_EXAMPLE}},
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def check_in_person_endpoint(
    person: str = Query(..., min_length=1, max_length=200, description="Person to check in with"),
    org: Organization = Depends(get_current_org),
):
    return await check_in_person(org.graph_name, person)


@router.post(
    "/check-in/auto",
    summary="Auto-detect who needs checking in",
    description=(
        "Scan the org's graph for people who need a proactive check-in — those "
        "with open commitments who have been silent for 4+ days or have overdue "
        "items. Generates a check-in message for each. This is what the PM agent "
        "would call on a schedule to proactively reach out without being asked."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "Auto check-in results",
            "content": {
                "application/json": {
                    "example": {
                        "graph_name": "org_abc123",
                        "check_ins": [CHECKIN_EXAMPLE],
                        "elapsed_ms": 3200,
                    }
                }
            },
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def check_in_auto_endpoint(org: Organization = Depends(get_current_org)):
    return await check_in_auto(org.graph_name)
