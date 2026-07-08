from __future__ import annotations

import enum
import re
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

FACT_NAMESPACE = uuid.UUID("7c9e6f5a-2b4d-4f1e-9a3c-8d7b6e5f4a3b")


class FactKind(str, enum.Enum):
    FACT = "fact"
    SKILL = "skill"
    STATUS_UPDATE = "status_update"
    COMMITMENT = "commitment"
    BLOCKER = "blocker"
    DECISION = "decision"
    REQUIREMENT = "requirement"
    IDEA = "idea"
    RISK = "risk"
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    IDENTITY = "identity"


SINGLE_VALUE_KINDS = {FactKind.IDENTITY, FactKind.AVAILABILITY}


class TemporalStatus(str, enum.Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class SpeakerRole(str, enum.Enum):
    FOUNDER = "founder"
    ENGINEER = "engineer"
    MARKETER = "marketer"
    MANAGER = "manager"
    ASSISTANT = "assistant"
    OTHER = "other"


def normalise_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def derive_fact_id(subject: str, predicate: str, value: str, topics: list[str]) -> str:
    signature = "|".join(
        [subject.strip().lower(), predicate.strip().lower(), value.strip().lower(), ",".join(sorted(topics))]
    )
    return str(uuid.uuid5(FACT_NAMESPACE, signature))


class Fact(BaseModel):
    fact_id: str = ""
    subject: str = Field(min_length=1, max_length=300)
    predicate: str = Field(min_length=1, max_length=150)
    value: str = Field(min_length=1, max_length=2000)
    fact_kind: FactKind = FactKind.FACT
    topics: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=16)
    project: str | None = None
    task: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    sentiment: str = "neutral"
    temporal_hint: str = "current"
    due_date: str | None = None
    evidence_quote: str | None = None
    speaker: str | None = None
    speaker_role: SpeakerRole = SpeakerRole.OTHER
    episode_id: str | None = None
    temporal_status: TemporalStatus = TemporalStatus.CURRENT
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: datetime | None = None
    superseded_by: str | None = None
    embedding: list[float] | None = None

    def model_post_init(self, __context) -> None:
        self.topics = [normalise_slug(t) for t in self.topics if t.strip()][:8]
        if not self.fact_id:
            self.fact_id = derive_fact_id(self.subject, self.predicate, self.value, self.topics)

    @property
    def embedding_text(self) -> str:
        parts = [f"{self.subject} {self.predicate} {self.value}"]
        if self.topics:
            parts.append(f"topics: {', '.join(self.topics)}")
        if self.entities:
            parts.append(f"entities: {', '.join(self.entities)}")
        return ". ".join(parts)


class IngestRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=200_000,
        description="The conversation message to ingest (founder chat, Slack message, etc.)",
        examples=[
            "I will ship the auth module by Friday. The OAuth token refresh is blocking me."
        ],
    )
    speaker: str = Field(min_length=1, max_length=200, description="Who said the message", examples=["Dave"])
    speaker_role: SpeakerRole = Field(SpeakerRole.OTHER, description="Role of the speaker")
    channel: str = Field("api", max_length=64, description="Source channel (slack, api, email, etc.)", examples=["slack"])
    session_id: str | None = Field(None, max_length=128, description="Optional session/conversation ID")
    project: str | None = Field(None, max_length=200, description="Optional project name to associate", examples=["api"])
    timestamp: datetime | None = Field(None, description="When the message occurred (defaults to now)")


class IngestAccepted(BaseModel):
    request_id: str
    status: str = "queued"


class IngestStatus(BaseModel):
    request_id: str
    status: str
    result: dict | None = None
    error: str | None = None


class AddFactRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    predicate: str = Field(min_length=1, max_length=150)
    value: str = Field(min_length=1, max_length=2000)
    fact_kind: FactKind = FactKind.FACT
    topics: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=16)
    project: str | None = None
    task: str | None = None


class FactRead(BaseModel):
    fact_id: str
    subject: str
    predicate: str
    value: str
    fact_kind: str
    topics: list[str]
    entities: list[str]
    project: str | None
    task: str | None
    sentiment: str
    temporal_status: str
    valid_from: datetime | None
    speaker: str | None
    due_date: str | None


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=4000,
        description="The question or query to retrieve context for",
        examples=["Is the API project on track? Any risks?"],
    )
    max_facts: int = Field(20, ge=1, le=100, description="Maximum facts to return")
    rerank: bool = Field(True, description="Use LLM associative reranking (slower but more accurate)")


class SearchResponse(BaseModel):
    query: str
    prompt_context: str
    facts: list[FactRead]
    associations: dict[str, dict]
    intent: dict
    project_states: list[dict] = Field(default_factory=list)
    person_states: list[dict] = Field(default_factory=list)
    elapsed_ms: int
