import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization
from kgmemory.worker import queue

from .repository import FactRepository
from .schemas import (
    AddFactRequest,
    Fact,
    FactRead,
    IngestAccepted,
    IngestRequest,
    IngestStatus,
)
from .tasks import get_status, set_status

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/ingest", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def ingest(payload: IngestRequest, org: Organization = Depends(get_current_org)):
    request_id = uuid.uuid4().hex
    await set_status(request_id, "queued")
    await queue.enqueue(
        "ingest_conversation",
        request_id=request_id,
        graph_name=org.graph_name,
        payload=payload.model_dump(mode="json"),
        key=f"ingest:{request_id}",
        retries=3,
    )
    return IngestAccepted(request_id=request_id)


@router.get("/ingest/{request_id}", response_model=IngestStatus)
async def ingest_status(request_id: str, org: Organization = Depends(get_current_org)):
    record = await get_status(request_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown request_id")
    return IngestStatus(**record)


@router.post("/facts", response_model=FactRead, status_code=status.HTTP_201_CREATED)
async def add_fact(payload: AddFactRequest, org: Organization = Depends(get_current_org)):
    from kgmemory.llm.embeddings import get_embedder

    fact = Fact(**payload.model_dump())
    fact.embedding = await get_embedder().embed(fact.embedding_text)
    repo = FactRepository(await get_org_store(org.graph_name))
    await repo.supersede_conflicting([fact])
    await repo.upsert_facts([fact])
    await repo.link_bridges([fact])
    data = fact.model_dump(include=set(FactRead.model_fields))
    return FactRead(**data)


@router.get("/facts", response_model=list[FactRead])
async def list_facts(
    org: Organization = Depends(get_current_org),
    subject: str | None = Query(None, max_length=300),
    topic: str | None = Query(None, max_length=100),
    project: str | None = Query(None, max_length=200),
    fact_kind: str | None = Query(None, max_length=50),
    current_only: bool = True,
    limit: int = Query(100, ge=1, le=500),
):
    repo = FactRepository(await get_org_store(org.graph_name))
    facts = await repo.list_facts(
        subject=subject,
        topic=topic,
        project=project,
        fact_kind=fact_kind,
        current_only=current_only,
        limit=limit,
    )
    return [FactRead(**fact) for fact in facts]


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_fact(fact_id: str, org: Organization = Depends(get_current_org)):
    repo = FactRepository(await get_org_store(org.graph_name))
    if not await repo.invalidate_fact(fact_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
