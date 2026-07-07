from datetime import datetime, timezone

import pytest

from kgmemory.memory.extraction import chunk_message, extract_facts
from kgmemory.memory.schemas import FactKind


def test_chunk_message_short():
    assert chunk_message("hello world") == ["hello world"]


def test_chunk_message_splits_long_paragraphs():
    long = "Sentence one. " * 1000
    chunks = chunk_message(long, chunk_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_chunk_message_respects_paragraphs():
    text = "para one\n\npara two"
    assert chunk_message(text) == [text]


@pytest.mark.asyncio
async def test_extract_facts_parses_llm_payload(monkeypatch):
    payload = {
        "facts": [
            {
                "local_id": "f0",
                "fact_kind": "commitment",
                "subject": "Dave",
                "predicate": "committed to",
                "value": "ship api by friday",
                "topics": ["api", "backend"],
                "entities": ["acme"],
                "due_date": "2026-07-10",
                "evidence_quote": "ship api by friday",
            }
        ],
        "relations": [],
    }

    async def fake_complete(self, prompt, **kwargs):
        import json

        return json.dumps(payload)

    monkeypatch.setattr(
        "kgmemory.llm.client.LLMClient.complete", fake_complete
    )

    facts, relations, failed = await extract_facts(
        "I will ship the api by friday",
        speaker="Dave",
        speaker_role="engineer",
        episode_id="ep1",
        timestamp=datetime(2026, 7, 7, tzinfo=timezone.utc),
        project="api",
    )
    assert failed == 0
    assert len(facts) == 1
    assert facts[0].fact_kind == FactKind.COMMITMENT
    assert facts[0].due_date == "2026-07-10"
    assert relations == []
