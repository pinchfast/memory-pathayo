import pytest

from kgmemory.state.decision import _format_person_states, _format_project_states


def test_format_project_states_empty():
    assert "no project states" in _format_project_states([])


def test_format_project_states_with_data():
    states = [
        {
            "project": "api",
            "health": "at_risk",
            "health_score": 0.4,
            "risk_signals": ["2 missed deadlines"],
            "summary": "Dave has been stalling on the auth module.",
        }
    ]
    text = _format_project_states(states)
    assert "api" in text
    assert "at_risk" in text
    assert "stalling" in text
    assert "2 missed deadlines" in text


def test_format_person_states_empty():
    assert "no person states" in _format_person_states([])


def test_format_person_states_with_data():
    states = [
        {
            "person": "dave",
            "credibility": "low",
            "credibility_score": 0.2,
            "risk_signals": ["not seen in 5 days"],
            "summary": "Dave has missed two deadlines and gone silent.",
        }
    ]
    text = _format_person_states(states)
    assert "dave" in text
    assert "low" in text
    assert "silent" in text


@pytest.mark.asyncio
async def test_decision_falls_back_on_llm_failure(monkeypatch):
    from kgmemory.state.decision import decide
    from kgmemory.state.schemas import DecisionRequest

    async def fake_search_context(graph_name, query, **kwargs):
        return {
            "query": query,
            "facts": [],
            "associations": {},
            "project_states": [],
            "person_states": [],
            "prompt_context": "No relevant memory found.",
            "elapsed_ms": 10,
        }

    async def failing_complete(self, prompt, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("kgmemory.state.decision.search_context", fake_search_context)
    monkeypatch.setattr("kgmemory.llm.client.LLMClient.complete", failing_complete)

    request = DecisionRequest(query="Is the api on track?", audience="founder_non_technical")
    result = await decide("org_test", request)
    assert "couldn't fully analyze" in result["response_text"]
    assert result["risk_level"] == "medium"
    assert result["reasoning"]
