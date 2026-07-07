
from kgmemory.contextengine.engine import _dense_rank, _render, _select
from kgmemory.contextengine.retrievers import recency_score


def test_recency_score_recent_is_high():
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).isoformat()
    assert recency_score(recent) > 0.9


def test_recency_score_old_is_low():
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    assert recency_score(old) < 0.2


def test_dense_rank_orders_by_score():
    facts = [
        {"fact_id": "a", "similarity": 0.9, "topics": ["api"], "valid_from": None},
        {"fact_id": "b", "similarity": 0.3, "topics": ["api"], "valid_from": None},
    ]
    ranked = _dense_rank(facts, ["api"])
    assert ranked[0]["fact_id"] == "a"
    assert ranked[0]["dense_score"] > ranked[1]["dense_score"]


def test_select_respects_budget():
    facts = [
        {"fact_id": str(i), "similarity": 0.5, "topics": [], "valid_from": None, "dense_score": 0.5}
        for i in range(10)
    ]
    selected = _select(facts, {}, budget=3, rerank=False)
    assert len(selected) == 3


def test_render_empty_returns_message():
    assert "No relevant" in _render([], {})


def test_render_includes_fact_content():
    facts = [
        {
            "fact_id": "1",
            "fact_kind": "commitment",
            "topics": ["api"],
            "subject": "Dave",
            "predicate": "committed to",
            "value": "ship api",
            "speaker": "Dave",
            "valid_from": "2026-07-07T10:00:00+00:00",
        }
    ]
    rendered = _render(facts, {})
    assert "Dave" in rendered
    assert "ship api" in rendered
