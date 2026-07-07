from kgmemory.memory.schemas import (
    Fact,
    FactKind,
    SpeakerRole,
    TemporalStatus,
    derive_fact_id,
    normalise_slug,
)


def test_normalise_slug():
    assert normalise_slug("Project Management") == "project_management"
    assert normalise_slug("  API-Design  ") == "api_design"
    assert normalise_slug("") == ""


def test_fact_id_is_deterministic():
    args = ("Alice", "is skilled in", "Python", ["python", "backend"])
    assert derive_fact_id(*args) == derive_fact_id(*args)


def test_fact_id_changes_with_value():
    base = derive_fact_id("Alice", "is skilled in", "Python", ["python"])
    different = derive_fact_id("Alice", "is skilled in", "Rust", ["rust"])
    assert base != different


def test_fact_model_derives_id_and_normalises_topics():
    fact = Fact(
        subject="Bob",
        predicate="completed",
        value="auth module",
        fact_kind=FactKind.STATUS_UPDATE,
        topics=["Auth System", "Backend"],
        entities=["acme"],
        speaker="Bob",
        speaker_role=SpeakerRole.ENGINEER,
    )
    assert fact.fact_id
    assert fact.topics == ["auth_system", "backend"]
    assert fact.temporal_status == TemporalStatus.CURRENT


def test_fact_embedding_text_includes_topics_and_entities():
    fact = Fact(
        subject="Carol",
        predicate="committed to",
        value="ship landing page",
        topics=["marketing"],
        entities=["acme", "stripe"],
    )
    text = fact.embedding_text
    assert "marketing" in text
    assert "stripe" in text
