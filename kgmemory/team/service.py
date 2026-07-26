"""Performance feedback and team morale sensing.

The PM generates honest, specific performance feedback for each engineer based
on their contribution data, and senses team morale from conversation sentiment
patterns.
"""
from __future__ import annotations

import time
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import MORALE_SENSING_PROMPT, PERFORMANCE_FEEDBACK_PROMPT
from kgmemory.people.service import compute_reliability, get_contributions, get_person, list_people


async def generate_performance_feedback(
    graph_name: str, engineer: str
) -> dict[str, Any]:
    """Generate honest, specific performance feedback for an engineer."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    person = await get_person(store, engineer)
    if not person:
        return {"error": "Person not found"}

    contributions = await get_contributions(store, engineer)
    reliability = await compute_reliability(store, engineer)

    # Get fulfilled and missed commitments
    fulfilled = contributions.get("fulfilled_commitments", 0)
    missed = reliability.get("missed_or_flagged", 0)
    total_commitments = reliability.get("commitments", 0)

    # Get skills demonstrated
    skills = person.get("skills") or []

    # Get recent work reviews (from decision history)
    review_rows = await store.query(
        "MATCH (d:DecisionHistory) WHERE d.query CONTAINS $engineer "
        "RETURN d.response_text, d.created_at ORDER BY d.created_at DESC LIMIT 3",
        {"engineer": engineer},
    )
    reviews = [r[0][:200] for r in review_rows] or ["No recent reviews"]

    # Format contributions summary
    by_kind = contributions.get("by_kind", {})
    contrib_summary = (
        f"Total facts: {contributions.get('total_facts', 0)}, "
        f"By kind: {by_kind}, "
        f"Fulfilled commitments: {fulfilled}, "
        f"Projects: {list(contributions.get('by_project', {}).keys())}"
    )

    prompt = PERFORMANCE_FEEDBACK_PROMPT.format(
        engineer=engineer,
        contributions=contrib_summary,
        reliability=f"{reliability.get('reliability_score', 0.5)} ({reliability.get('commitments', 0)} commitments)",
        fulfilled=fulfilled,
        missed=missed,
        reviews="\n".join(reviews),
        skills=", ".join(skills) or "No skills recorded",
    )

    try:
        response = await get_llm().complete(prompt, kind="feedback", max_tokens=800)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Performance feedback payload is not an object")
    except Exception as exc:
        logger.exception(f"Performance feedback LLM failed: {exc}")
        rating = "meeting"
        if reliability.get("reliability_score", 0.5) >= 0.7:
            rating = "exceeding"
        elif reliability.get("reliability_score", 0.5) < 0.3:
            rating = "concerning"
        elif reliability.get("reliability_score", 0.5) < 0.5:
            rating = "below"
        payload = {
            "feedback_summary": (
                f"{engineer} has {fulfilled} fulfilled commitments and {missed} missed. "
                f"Reliability score is {reliability.get('reliability_score', 0.5)}."
            ),
            "strengths": ["Consistent contribution to the project"] if total_commitments > 0 else [],
            "areas_for_growth": ["Improve deadline adherence"] if missed > 0 else [],
            "overall_rating": rating,
            "message_to_engineer": (
                f"Hi {engineer}, you've completed {fulfilled} commitments. "
                + ("Keep up the good work!" if missed == 0 else f"Let's work on improving your {missed} missed deadlines.")
            ),
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["engineer"] = engineer
    payload["reliability_score"] = reliability.get("reliability_score", 0.5)
    payload["fulfilled_commitments"] = fulfilled
    payload["missed_commitments"] = missed
    payload["elapsed_ms"] = elapsed
    return payload


async def sense_team_morale(graph_name: str) -> dict[str, Any]:
    """Sense team morale from conversation sentiment patterns."""
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    # Get sentiment distribution per person
    people = await list_people(store)
    sentiment_data = []
    for p in people:
        name = p["name"]
        sentiment_rows = await store.query(
            "MATCH (p:Person {name: $name})-[:STATED]->(f:Fact) "
            "WHERE f.temporal_status = 'current' AND f.valid_from >= $cutoff "
            "RETURN f.sentiment, count(f) ORDER BY count(f) DESC",
            {"name": name, "cutoff": _days_ago(14)},
        )
        sentiments = {r[0]: int(r[1]) for r in sentiment_rows}
        total = sum(sentiments.values())
        negative_pct = (sentiments.get("negative", 0) / total * 100) if total > 0 else 0
        sentiment_data.append({
            "person": name,
            "sentiments": sentiments,
            "total": total,
            "negative_pct": round(negative_pct, 1),
        })

    # Get recent blockers
    blocker_rows = await store.query(
        "MATCH (f:Fact) WHERE f.fact_kind = 'blocker' AND f.temporal_status = 'current' "
        "AND f.valid_from >= $cutoff "
        "RETURN f.value, f.subject, f.sentiment",
        {"cutoff": _days_ago(14)},
    )
    blockers = [f"{r[1]}: {r[0]} (sentiment: {r[2]})" for r in blocker_rows] or ["No recent blockers"]

    # Get complaints / negative language
    complaint_rows = await store.query(
        "MATCH (f:Fact) WHERE f.sentiment = 'negative' AND f.temporal_status = 'current' "
        "AND f.valid_from >= $cutoff "
        "RETURN f.value, f.subject, f.valid_from ORDER BY f.valid_from DESC LIMIT 10",
        {"cutoff": _days_ago(14)},
    )
    complaints = [f"{r[1]}: {r[0]}" for r in complaint_rows] or ["No recent complaints"]

    # Get silence patterns (people with no facts in last 7 days)
    silence_rows = await store.query(
        "MATCH (p:Person) WHERE NOT EXISTS { "
        "  MATCH (p)-[:STATED]->(f:Fact) WHERE f.valid_from >= $cutoff "
        "} RETURN p.name",
        {"cutoff": _days_ago(7)},
    )
    silence = [r[0] for r in silence_rows] or ["Everyone has been active"]

    prompt = MORALE_SENSING_PROMPT.format(
        sentiment_data="\n".join(
            f"- {s['person']}: {s['total']} facts, {s['negative_pct']}% negative"
            for s in sentiment_data
        ) or "No sentiment data",
        blockers="\n".join(blockers),
        complaints="\n".join(complaints),
        silence="\n".join(silence),
    )

    try:
        response = await get_llm().complete(prompt, kind="morale", max_tokens=800)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Morale sensing payload is not an object")
    except Exception as exc:
        logger.exception(f"Morale sensing LLM failed: {exc}")
        # Fallback: deterministic morale from negative sentiment percentage
        avg_negative = (
            sum(s["negative_pct"] for s in sentiment_data) / len(sentiment_data)
            if sentiment_data else 0
        )
        if avg_negative > 40:
            morale = "concerning"
        elif avg_negative > 25:
            morale = "declining"
        elif avg_negative > 10:
            morale = "stable"
        else:
            morale = "high"
        score = max(0.0, min(1.0, 1.0 - avg_negative / 100))
        payload = {
            "team_morale": morale,
            "morale_score": round(score, 2),
            "concerns": [f"High negative sentiment from {s['person']}" for s in sentiment_data if s["negative_pct"] > 30],
            "positive_signals": [],
            "recommended_actions": ["Check in with frustrated team members"] if avg_negative > 25 else [],
            "should_warn_founder": avg_negative > 30,
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["elapsed_ms"] = elapsed
    payload["people_analyzed"] = len(sentiment_data)
    return payload


def _days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
