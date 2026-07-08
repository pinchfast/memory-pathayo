from fastapi import APIRouter, Depends

from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .decision import decide
from .inference import infer_and_snapshot_state
from .schemas import DecisionRequest, DecisionResponse, StateInferenceResult

router = APIRouter(prefix="/pm", tags=["pm-brain"])


@router.post("/decide", response_model=DecisionResponse)
async def decide_endpoint(payload: DecisionRequest, org: Organization = Depends(get_current_org)):
    result = await decide(org.graph_name, payload)
    return DecisionResponse(**result)


@router.post("/infer-state", response_model=StateInferenceResult)
async def infer_state_endpoint(org: Organization = Depends(get_current_org)):
    result = await infer_and_snapshot_state(org.graph_name)
    return StateInferenceResult(**result)
