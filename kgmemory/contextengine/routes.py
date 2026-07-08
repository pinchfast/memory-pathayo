from fastapi import APIRouter, Depends

from kgmemory.core.metrics import SEARCHES
from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.memory.schemas import SearchRequest, SearchResponse
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .engine import search_context

router = APIRouter(prefix="/context", tags=["context"])

SEARCH_EXAMPLE = {
    "query": "Is the API project on track? Any risks?",
    "max_facts": 20,
    "rerank": True,
}


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid context search",
    description=(
        "Retrieve relevant memory for a query using hybrid retrieval: LLM intent "
        "extraction → parallel vector ANN + graph traversal + recency → optional "
        "LLM associative rerank. Returns a prompt-context string (markdown), "
        "structured facts with relevance scores, and current project/person states. "
        "This is the primary endpoint the Django backend calls to give the PM agent "
        "its memory before generating a response."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "Search results with context",
            "content": {
                "application/json": {
                    "example": {
                        "query": "Is the API project on track?",
                        "prompt_context": "RELEVANT COMPANY MEMORY:\n- [commitment|api] Dave committed to ship auth module...",
                        "facts": [],
                        "associations": {},
                        "intent": {"topics": ["api", "auth", "deadline"], "entities": ["Dave"]},
                        "project_states": [{"project": "api", "health": "at_risk", "health_score": 0.4}],
                        "person_states": [{"person": "dave", "credibility": "moderate", "credibility_score": 0.5}],
                        "elapsed_ms": 1200,
                    }
                }
            },
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def search(payload: SearchRequest, org: Organization = Depends(get_current_org)):
    SEARCHES.labels(org.graph_name).inc()
    result = await search_context(
        org.graph_name, payload.query, max_facts=payload.max_facts, rerank=payload.rerank
    )
    return SearchResponse(
        query=result["query"],
        prompt_context=result["prompt_context"],
        facts=result["facts"],
        associations=result["associations"],
        intent=result["intent"],
        project_states=result.get("project_states", []),
        person_states=result.get("person_states", []),
        elapsed_ms=result["elapsed_ms"],
    )
