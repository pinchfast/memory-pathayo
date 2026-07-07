from fastapi import APIRouter, Depends

from kgmemory.core.metrics import SEARCHES
from kgmemory.memory.schemas import SearchRequest, SearchResponse
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .engine import search_context

router = APIRouter(prefix="/context", tags=["context"])


@router.post("/search", response_model=SearchResponse)
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
        elapsed_ms=result["elapsed_ms"],
    )
