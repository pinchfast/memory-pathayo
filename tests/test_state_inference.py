from kgmemory.state.inference import (
    _deterministic_person_credibility,
    _deterministic_project_health,
    _days_since,
)


def test_project_health_on_track():
    signals = {
        "commitments": [],
        "completed": [{"speaker": "dave", "value": "shipped api", "valid_from": "2026-07-07"}],
        "missed": [],
        "blockers": [],
        "engineers": {"dave"},
        "last_activity": "2026-07-07T10:00:00+00:00",
        "facts": [],
    }
    result = _deterministic_project_health(signals)
    assert result["health"] == "on_track"
    assert result["health_score"] > 0.5


def test_project_health_blocked():
    signals = {
        "commitments": [],
        "completed": [],
        "missed": [],
        "blockers": [{"speaker": "dave", "value": "db migration stuck"}],
        "engineers": {"dave"},
        "last_activity": "2026-07-07T10:00:00+00:00",
        "facts": [],
    }
    result = _deterministic_project_health(signals)
    assert result["health"] == "blocked"
    assert "open blockers" in result["risk_signals"][0]


def test_project_health_delayed():
    signals = {
        "commitments": [{"speaker": "dave", "value": "ship by friday", "due_date": "2026-07-04"}],
        "completed": [],
        "missed": [
            {"speaker": "dave", "value": "missed deadline", "valid_from": "2026-07-05"},
            {"speaker": "dave", "value": "vague update", "valid_from": "2026-07-06"},
        ],
        "blockers": [],
        "engineers": {"dave"},
        "last_activity": "2026-07-06T10:00:00+00:00",
        "facts": [],
    }
    result = _deterministic_project_health(signals)
    assert result["health"] == "delayed"
    assert result["health_score"] < 0.5


def test_person_credibility_high():
    signals = {
        "commitments": [{"value": "ship auth", "due_date": "2026-07-10"}],
        "completed": [
            {"value": "shipped login", "valid_from": "2026-07-05"},
            {"value": "shipped api", "valid_from": "2026-07-06"},
        ],
        "missed": [],
        "last_seen": "2026-07-07T10:00:00+00:00",
        "facts": [],
    }
    result = _deterministic_person_credibility(signals)
    assert result["credibility"] == "high"
    assert result["credibility_score"] > 0.6


def test_person_credibility_low():
    signals = {
        "commitments": [{"value": "ship auth", "due_date": "2026-07-01"}],
        "completed": [],
        "missed": [
            {"value": "missed deadline", "valid_from": "2026-07-02"},
            {"value": "vague update", "valid_from": "2026-07-03"},
        ],
        "last_seen": "2026-07-03T10:00:00+00:00",
        "facts": [],
    }
    result = _deterministic_person_credibility(signals)
    assert result["credibility"] == "low"
    assert result["credibility_score"] < 0.4


def test_days_since_recent():
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).isoformat()
    assert _days_since(recent) == 0


def test_days_since_old():
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    assert _days_since(old) == 10


def test_days_since_none():
    assert _days_since(None) is None
