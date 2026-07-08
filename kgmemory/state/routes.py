from fastapi import APIRouter, Depends

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

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
