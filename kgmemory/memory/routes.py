import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization
from kgmemory.worker import queue

from .repository import FactRepository
from .schemas import (
    AddFactRequest,
    BatchIngestAccepted,
    BatchIngestRequest,
    Fact,
    FactRead,
    IngestAccepted,
    IngestRequest,
    IngestStatus,
)
from .tasks import get_status, set_status

router = APIRouter(prefix="/memory", tags=["memory"])

INGEST_EXAMPLE = {
    "message": "I will ship the auth module by Friday. The OAuth token refresh is blocking me.",
    "speaker": "Dave",
    "speaker_role": "engineer",
    "channel": "slack",
    "project": "api",
}
INGEST_RESPONSE_EXAMPLE = {"request_id": "a1b2c3d4e5f6", "status": "queued"}


@router.post(
    "/ingest",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a conversation message",
    description=(
        "Accept a conversation message (founder chat, Slack message, etc.) for async "
        "processing. The worker extracts facts via LLM, embeds them, deduplicates, "
        "and stores them in the org's knowledge graph. State inference runs "
        "automatically after ingest. Returns a `request_id` immediately — poll "
        "`GET /memory/ingest/{request_id}` for the result."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        202: {
            "description": "Ingest accepted and queued",
            "content": {"application/json": {"example": INGEST_RESPONSE_EXAMPLE}},
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def ingest(
    payload: IngestRequest,
    org: Organization = Depends(get_current_org),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=128),
):
    # Idempotency: if a key is provided, check for a prior result
    if idempotency_key:
        cached = await get_status(f"idem:{org.id}:{idempotency_key}")
        if cached:
            return IngestAccepted(request_id=cached["request_id"])

    request_id = uuid.uuid4().hex
    await set_status(request_id, "queued")
    # Store idempotency mapping so retries return the same request_id
    if idempotency_key:
        from kgmemory.memory.tasks import set_status as _set_status
        await _set_status(f"idem:{org.id}:{idempotency_key}", "queued", result={"request_id": request_id})
    await queue.enqueue(
        "ingest_conversation",
        request_id=request_id,
        graph_name=org.graph_name,
        payload=payload.model_dump(mode="json"),
        key=f"ingest:{request_id}",
        retries=3,
    )
    return IngestAccepted(request_id=request_id)


@router.post(
    "/ingest/batch",
    response_model=BatchIngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch ingest multiple messages",
    description=(
        "Accept up to 500 conversation messages at once for async processing. "
        "Ideal for importing Slack history, email threads, or backfilling on "
        "day one. Facts are extracted from all messages, embedded in a single "
        "batch, and state inference runs once after the entire batch. Returns "
        "a `request_id` — poll `GET /memory/ingest/{request_id}` for the result."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        202: {
            "description": "Batch ingest accepted and queued",
            "content": {
                "application/json": {
                    "example": {"request_id": "a1b2c3d4e5f6", "status": "queued", "message_count": 42},
                }
            },
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def ingest_batch(payload: BatchIngestRequest, org: Organization = Depends(get_current_org)):
    request_id = uuid.uuid4().hex
    await set_status(request_id, "queued")
    await queue.enqueue(
        "ingest_batch_conversation",
        request_id=request_id,
        graph_name=org.graph_name,
        messages=[m.model_dump(mode="json") for m in payload.messages],
        key=f"ingest:{request_id}",
        retries=2,
    )
    return BatchIngestAccepted(request_id=request_id, message_count=len(payload.messages))


@router.get(
    "/ingest/{request_id}",
    response_model=IngestStatus,
    summary="Check ingest job status",
    description=(
        "Poll the status of an async ingest job. States: `queued` → `running` → "
        "`complete` (with result) or `failed` (with error). Results are retained "
        "for 1 hour."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def ingest_status(request_id: str, org: Organization = Depends(get_current_org)):
    record = await get_status(request_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown request_id")
    return IngestStatus(**record)


@router.post(
    "/facts",
    response_model=FactRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a fact manually",
    description=(
        "Add a fact directly without LLM extraction. Useful for structured data "
        "imports or corrections. The fact is embedded and stored in the graph. "
        "Single-valued facts (identity, availability) will supersede existing ones."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        201: {
            "description": "Fact created",
            "content": {
                "application/json": {
                    "example": {
                        "fact_id": "a1b2c3d4",
                        "subject": "Dave",
                        "predicate": "is skilled in",
                        "value": "Python",
                        "fact_kind": "skill",
                        "topics": ["python", "backend"],
                        "entities": [],
                        "project": None,
                        "task": None,
                        "sentiment": "neutral",
                        "temporal_status": "current",
                        "valid_from": "2026-07-08T10:00:00Z",
                        "speaker": None,
                        "due_date": None,
                    }
                }
            },
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
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


@router.get(
    "/facts",
    response_model=list[FactRead],
    summary="List facts",
    description=(
        "List facts for the org, optionally filtered by subject, topic, project, "
        "or fact kind. Only current (non-superseded) facts are returned by default."
    ),
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def list_facts(
    org: Organization = Depends(get_current_org),
    subject: str | None = Query(None, max_length=300, description="Filter by subject (substring match)"),
    topic: str | None = Query(None, max_length=100, description="Filter by topic slug"),
    project: str | None = Query(None, max_length=200, description="Filter by project name"),
    fact_kind: str | None = Query(None, max_length=50, description="Filter by fact kind"),
    current_only: bool = Query(True, description="Only return current (non-superseded) facts"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
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


@router.delete(
    "/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate a fact",
    description="Mark a fact as invalidated (no longer current). Does not delete it — the fact remains in the graph for history.",
    responses={**ORG_PROTECTED_RESPONSES, 204: {"description": "Fact invalidated"}},
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def invalidate_fact(fact_id: str, org: Organization = Depends(get_current_org)):
    repo = FactRepository(await get_org_store(org.graph_name))
    if not await repo.invalidate_fact(fact_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
