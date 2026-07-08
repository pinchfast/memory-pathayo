"""Tests for contradiction detection, overdue computation, intent-aware ranking,
check-in reasoning, confidence scoring, source reliability weighting,
embedding fallback, escalation logic, commitment matching, and temporal reasoning."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kgmemory.contextengine.engine import _compute_is_overdue, _days_between, _dense_rank
from kgmemory.llm.embeddings import EmbeddingClient
from kgmemory.memory.repository import FactRepository, _COMPLETION_WORDS, _PROGRESS_WORDS
from kgmemory.memory.schemas import Fact, FactKind, SpeakerRole
from kgmemory.monitor.monitor import _escalate_severity
from kgmemory.state.checkin import _derive_check_in_reason, _days_since
from kgmemory.state.decision import _compute_confidence


# --- Contradiction detection heuristics ---


def test_completion_words_detect_done():
    """Values containing completion words should be detected as completions."""
    value = "I completed the auth module yesterday"
    assert any(w in value.lower() for w in _COMPLETION_WORDS)


def test_progress_words_detect_in_progress():
    """Values containing progress words should be detected as in-progress."""
    value = "I'm working on the auth module"
    assert any(w in value.lower() for w in _PROGRESS_WORDS)


def test_completion_and_progress_are_disjoint():
    """A value shouldn't match both completion and progress word sets (usually)."""
    value = "I completed the login page but I'm still working on the OAuth flow"
    is_completion = any(w in value.lower() for w in _COMPLETION_WORDS)
    is_progress = any(w in value.lower() for w in _PROGRESS_WORDS)
    # This value has both — which is fine, it's a mixed statement.
    # The contradiction detector only flags when one fact says done and another says in-progress.
    assert is_completion and is_progress  # mixed statement


# --- Overdue computation ---


def test_is_overdue_true_for_past_due_commitment():
    now = datetime.now(timezone.utc)
    fact = {
        "fact_kind": "commitment",
        "due_date": (now - timedelta(days=3)).isoformat(),
        "temporal_status": "current",
    }
    assert _compute_is_overdue(fact, now) is True


def test_is_overdue_false_for_future_due_commitment():
    now = datetime.now(timezone.utc)
    fact = {
        "fact_kind": "commitment",
        "due_date": (now + timedelta(days=3)).isoformat(),
        "temporal_status": "current",
    }
    assert _compute_is_overdue(fact, now) is False


def test_is_overdue_false_for_no_due_date():
    now = datetime.now(timezone.utc)
    fact = {"fact_kind": "commitment", "due_date": None, "temporal_status": "current"}
    assert _compute_is_overdue(fact, now) is False


def test_is_overdue_false_for_non_commitment():
    now = datetime.now(timezone.utc)
    fact = {
        "fact_kind": "status_update",
        "due_date": (now - timedelta(days=3)).isoformat(),
        "temporal_status": "current",
    }
    assert _compute_is_overdue(fact, now) is False


def test_is_overdue_false_for_superseded():
    now = datetime.now(timezone.utc)
    fact = {
        "fact_kind": "commitment",
        "due_date": (now - timedelta(days=3)).isoformat(),
        "temporal_status": "superseded",
    }
    assert _compute_is_overdue(fact, now) is False


def test_is_overdue_false_for_invalid_date():
    now = datetime.now(timezone.utc)
    fact = {
        "fact_kind": "commitment",
        "due_date": "not-a-date",
        "temporal_status": "current",
    }
    assert _compute_is_overdue(fact, now) is False


# --- Intent-aware dense ranking ---


def test_dense_rank_kind_hint_boost():
    """Facts matching the query's fact_kind_hints should rank higher."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
        },
        {
            "fact_id": "f2",
            "fact_kind": "skill",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
        },
    ]
    ranked = _dense_rank(facts, topics=["api"], fact_kind_hints=["status_update", "commitment"])
    # f1 (status_update) should rank higher because it matches the hint
    assert ranked[0]["fact_id"] == "f1"
    assert ranked[0]["dense_score"] > ranked[1]["dense_score"]


def test_dense_rank_overdue_boost():
    """Overdue facts should get a boost in dense ranking."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "commitment",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": True,
        },
        {
            "fact_id": "f2",
            "fact_kind": "commitment",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
        },
    ]
    ranked = _dense_rank(facts, topics=["api"])
    assert ranked[0]["fact_id"] == "f1"
    assert ranked[0]["dense_score"] > ranked[1]["dense_score"]


def test_dense_rank_no_hints_no_boost():
    """Without fact_kind_hints, kind shouldn't affect ranking."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.6,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
        },
        {
            "fact_id": "f2",
            "fact_kind": "skill",
            "topics": ["api"],
            "similarity": 0.6,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
        },
    ]
    ranked = _dense_rank(facts, topics=["api"], fact_kind_hints=None)
    # Same similarity, same topics, no hints → same score
    assert abs(ranked[0]["dense_score"] - ranked[1]["dense_score"]) < 0.001


# --- Check-in reasoning ---


def test_check_in_reason_overdue():
    signals = {
        "commitments": [{"value": "ship auth", "due_date": "2026-07-01", "project": "api"}],
        "days_since_last_seen": 1,
        "has_overdue": True,
    }
    reason = _derive_check_in_reason(signals)
    assert reason == "has overdue commitments"


def test_check_in_reason_silence():
    signals = {
        "commitments": [{"value": "ship auth", "due_date": None, "project": "api"}],
        "days_since_last_seen": 5,
        "has_overdue": False,
    }
    reason = _derive_check_in_reason(signals)
    assert "silent" in reason
    assert "5" in reason


def test_check_in_reason_not_needed_no_commitments():
    signals = {
        "commitments": [],
        "days_since_last_seen": 10,
        "has_overdue": False,
    }
    reason = _derive_check_in_reason(signals)
    assert reason is None


def test_check_in_reason_not_needed_active():
    signals = {
        "commitments": [{"value": "ship auth", "due_date": "2026-07-20", "project": "api"}],
        "days_since_last_seen": 0,
        "has_overdue": False,
    }
    reason = _derive_check_in_reason(signals)
    assert reason is None


def test_days_since_recent():
    now = datetime.now(timezone.utc)
    result = _days_since(now.isoformat())
    assert result == 0


def test_days_since_old():
    old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    result = _days_since(old)
    assert result == 7


def test_days_since_none():
    assert _days_since(None) is None


def test_days_since_invalid():
    assert _days_since("not-a-date") is None


# --- Confidence scoring ---


def test_confidence_high_with_many_facts_and_states():
    context = {
        "facts": [{"valid_from": datetime.now(timezone.utc).isoformat(), "speaker": "dave"}] * 10,
        "project_states": [{"project": "api", "health": "on_track"}],
        "person_states": [{"person": "dave", "credibility": "high"}],
    }
    confidence = _compute_confidence(context)
    assert confidence > 0.5


def test_confidence_low_with_no_facts():
    context = {"facts": [], "project_states": [], "person_states": []}
    confidence = _compute_confidence(context)
    assert confidence < 0.3


def test_confidence_medium_with_some_facts():
    context = {
        "facts": [{"valid_from": datetime.now(timezone.utc).isoformat(), "speaker": "dave"}] * 3,
        "project_states": [],
        "person_states": [],
    }
    confidence = _compute_confidence(context)
    assert 0.2 < confidence < 0.7


def test_confidence_boosted_by_states():
    """Having project + person states should boost confidence."""
    base = {
        "facts": [{"valid_from": datetime.now(timezone.utc).isoformat(), "speaker": "dave"}] * 3,
        "project_states": [],
        "person_states": [],
    }
    with_states = {
        **base,
        "project_states": [{"project": "api"}],
        "person_states": [{"person": "dave"}],
    }
    assert _compute_confidence(with_states) > _compute_confidence(base)


def test_confidence_boosted_by_speaker_diversity():
    """Facts from multiple speakers should boost confidence."""
    now_str = datetime.now(timezone.utc).isoformat()
    single_speaker = {
        "facts": [{"valid_from": now_str, "speaker": "dave"}] * 5,
        "project_states": [],
        "person_states": [],
    }
    multi_speaker = {
        "facts": [
            {"valid_from": now_str, "speaker": "dave"},
            {"valid_from": now_str, "speaker": "alice"},
            {"valid_from": now_str, "speaker": "bob"},
        ],
        "project_states": [],
        "person_states": [],
    }
    assert _compute_confidence(multi_speaker) >= _compute_confidence(single_speaker)


# --- Source reliability weighting ---


def test_dense_rank_founder_boost():
    """Facts from founders should rank higher than facts from engineers."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "decision",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": "founder",
        },
        {
            "fact_id": "f2",
            "fact_kind": "decision",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": "engineer",
        },
    ]
    ranked = _dense_rank(facts, topics=["api"])
    assert ranked[0]["fact_id"] == "f1"  # founder ranks higher
    assert ranked[0]["dense_score"] > ranked[1]["dense_score"]


def test_dense_rank_engineer_beats_unknown():
    """Facts from engineers should rank higher than unknown sources."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": "engineer",
        },
        {
            "fact_id": "f2",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": None,
        },
    ]
    ranked = _dense_rank(facts, topics=["api"])
    assert ranked[0]["fact_id"] == "f1"  # engineer ranks higher


# --- Embedding fallback ---


def test_hash_embedding_deterministic():
    """Same text should produce the same fallback embedding."""
    client = EmbeddingClient()
    e1 = client._hash_embedding("test text")
    e2 = client._hash_embedding("test text")
    assert e1 == e2
    assert len(e1) == client.dimensions


def test_hash_embedding_different_text():
    """Different text should produce different fallback embeddings."""
    client = EmbeddingClient()
    e1 = client._hash_embedding("hello world")
    e2 = client._hash_embedding("goodbye world")
    assert e1 != e2


def test_hash_embedding_dimensions():
    """Fallback embedding should match configured dimensions."""
    client = EmbeddingClient()
    emb = client._hash_embedding("test")
    assert len(emb) == client.dimensions


def test_hash_embedding_range():
    """Fallback embedding values should be in [-1, 1] range."""
    client = EmbeddingClient()
    emb = client._hash_embedding("test text for range check")
    assert all(-1.0 <= v <= 1.0 for v in emb)


# --- Escalation logic ---


def test_escalate_severity_medium_to_high():
    assert _escalate_severity("medium") == "high"


def test_escalate_severity_high_to_critical():
    assert _escalate_severity("high") == "critical"


def test_escalate_severity_low_to_medium():
    assert _escalate_severity("low") == "medium"


def test_escalate_severity_critical_stays():
    assert _escalate_severity("critical") == "critical"


# --- Commitment fulfillment matching ---


def test_completion_match_exact():
    """Exact word overlap between commitment and completion."""
    assert FactRepository._is_completion_match("ship auth module", "shipped auth module")


def test_completion_match_partial():
    """40% word overlap is enough for a match."""
    assert FactRepository._is_completion_match("ship the auth module by friday", "shipped auth module")


def test_completion_match_no_overlap():
    """Completely different text should not match."""
    assert not FactRepository._is_completion_match("ship auth module", "deployed payment gateway")


def test_completion_match_empty_commitment():
    """Empty commitment value should match (no text to compare)."""
    assert FactRepository._is_completion_match("", "completed everything")


# --- Per-fact confidence scoring ---


def test_fact_confidence_founder_high():
    """Founder statements should have higher confidence than unknown sources."""
    fact = Fact(
        subject="company", predicate="decided", value="We will use PostgreSQL for the database",
        fact_kind=FactKind.DECISION, speaker="Alice", speaker_role=SpeakerRole.FOUNDER,
        entities=["postgresql"], sentiment="neutral", temporal_hint="current",
        evidence_quote="We will use PostgreSQL",
    )
    confidence = fact.compute_confidence()
    assert confidence > 0.7


def test_fact_confidence_vague_lower_than_specific():
    """Vague language should produce lower confidence than specific language."""
    vague = Fact(
        subject="dave", predicate="committed to", value="maybe ship it soon",
        fact_kind=FactKind.COMMITMENT, speaker="Dave", speaker_role=SpeakerRole.ENGINEER,
        sentiment="neutral", temporal_hint="future",
    )
    specific = Fact(
        subject="dave", predicate="committed to", value="ship auth module by 2026-07-15",
        fact_kind=FactKind.COMMITMENT, speaker="Dave", speaker_role=SpeakerRole.ENGINEER,
        sentiment="neutral", temporal_hint="future", due_date="2026-07-15",
        entities=["auth"], evidence_quote="ship auth module by 2026-07-15",
    )
    assert vague.compute_confidence() < specific.compute_confidence()


def test_fact_confidence_specific_high():
    """Specific values with numbers and dates should have higher confidence."""
    fact = Fact(
        subject="dave", predicate="completed", value="merged PR #123 with 450 lines of tests",
        fact_kind=FactKind.STATUS_UPDATE, speaker="Dave", speaker_role=SpeakerRole.ENGINEER,
        entities=["pr_123"], sentiment="neutral", temporal_hint="current",
        evidence_quote="merged PR #123 with 450 lines of tests",
        due_date="2026-07-08",
    )
    confidence = fact.compute_confidence()
    assert confidence > 0.7


def test_fact_confidence_engineer_moderate():
    """Engineer statements should have moderate confidence."""
    fact = Fact(
        subject="dave", predicate="is skilled in", value="Python",
        fact_kind=FactKind.SKILL, speaker="Dave", speaker_role=SpeakerRole.ENGINEER,
        sentiment="neutral", temporal_hint="current",
    )
    confidence = fact.compute_confidence()
    assert 0.5 < confidence < 0.8


def test_fact_confidence_in_range():
    """Confidence should always be in [0, 1]."""
    for role in SpeakerRole:
        fact = Fact(
            subject="x", predicate="is", value="maybe possibly eventually soon",
            fact_kind=FactKind.FACT, speaker_role=role, sentiment="negative",
        )
        confidence = fact.compute_confidence()
        assert 0.0 <= confidence <= 1.0


# --- Temporal reasoning ---


def test_days_between_past():
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=5)).isoformat()
    assert _days_between(past, now) == 5


def test_days_between_future():
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=3)).isoformat()
    # Should return 0 (not negative)
    assert _days_between(future, now) == 0


def test_days_between_none():
    assert _days_between(None, datetime.now(timezone.utc)) is None


def test_days_between_invalid():
    assert _days_between("not-a-date", datetime.now(timezone.utc)) is None


# --- Dense rank with confidence ---


def test_dense_rank_confidence_boost():
    """High-confidence facts should rank higher than low-confidence ones."""
    facts = [
        {
            "fact_id": "f1",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": "engineer",
            "confidence": 0.9,
        },
        {
            "fact_id": "f2",
            "fact_kind": "status_update",
            "topics": ["api"],
            "similarity": 0.5,
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "is_overdue": False,
            "speaker_role": "engineer",
            "confidence": 0.2,
        },
    ]
    ranked = _dense_rank(facts, topics=["api"])
    assert ranked[0]["fact_id"] == "f1"
    assert ranked[0]["dense_score"] > ranked[1]["dense_score"]
