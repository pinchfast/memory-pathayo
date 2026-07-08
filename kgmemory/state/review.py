"""Honest work review and next-step planning.

When an engineer reports "I finished X", the PM evaluates the claim honestly:
- Does the claim match the original commitment?
- Is there concrete evidence or just "I finished it"?
- Based on their credibility, how much should we trust this?
- What's missing? What should we ask to verify?

Then the PM plans next steps collaboratively with the engineer.
"""
from __future__ import annotations

import time
from typing import Any

from kgmemory.contextengine.engine import search_context
from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import NEXT_STEPS_PROMPT, WORK_REVIEW_PROMPT
from kgmemory.people.service import get_person
from kgmemory.projects.service import list_tasks


async def review_work(
    graph_name: str,
    engineer: str,
    claim: str,
    project: str | None = None,
) -> dict[str, Any]:
    """Review work that an engineer claims to have completed.
    Returns an honest assessment with verification questions and founder message.
    """
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    # Get the engineer's credibility
    person = await get_person(store, engineer)
    credibility = "unknown"
    credibility_score = 0.5
    if person:
        reliability = person.get("reliability") or {}
        credibility_score = reliability.get("reliability_score", 0.5)
        if credibility_score >= 0.7:
            credibility = "high"
        elif credibility_score >= 0.4:
            credibility = "moderate"
        else:
            credibility = "low"

    # Search for the original commitment and project context
    context = await search_context(
        graph_name,
        f"{engineer} commitment {claim}",
        max_facts=10,
        rerank=False,
    )
    facts = context.get("facts") or []

    # Find the original commitment
    original_commitment = "No specific commitment found matching this claim."
    for fact in facts:
        if fact.get("fact_kind") == "commitment" and fact.get("speaker", "").lower() == engineer.lower().strip():
            original_commitment = f"{fact.get('subject')} {fact.get('predicate')} {fact.get('value')}"
            if fact.get("due_date"):
                original_commitment += f" (due: {fact['due_date'][:10]})"
            break

    # Build project context from facts
    project_context = "\n".join(
        f"- [{f.get('fact_kind')}] {f.get('subject')} {f.get('predicate')} {f.get('value')}"
        for f in facts[:8]
    ) or "No project context available."

    # Check for evidence in the claim
    evidence = _extract_evidence(claim)

    prompt = WORK_REVIEW_PROMPT.format(
        engineer=engineer,
        claim=claim,
        evidence=evidence,
        credibility=f"{credibility} (score: {credibility_score})",
        commitment=original_commitment,
        project_context=project_context,
    )

    try:
        response = await get_llm().complete(prompt, kind="review", max_tokens=1000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Work review payload is not an object")
    except Exception as exc:
        logger.exception(f"Work review LLM failed: {exc}")
        payload = {
            "assessment": "unverified",
            "confidence_in_claim": 0.3,
            "what_was_done": claim,
            "what_is_missing": "Unable to assess — LLM review failed.",
            "honest_review": f"I couldn't fully verify {engineer}'s claim. They say: {claim}. I'd recommend asking for specifics.",
            "questions_for_engineer": ["Can you share more details about what you completed?"],
            "next_steps": ["Ask for specific evidence of completion"],
            "should_notify_founder": True,
            "founder_message": f"{engineer} reports they completed: {claim}. I haven't been able to verify this yet.",
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["engineer"] = engineer
    payload["elapsed_ms"] = elapsed
    return payload


async def plan_next_steps(
    graph_name: str,
    engineer: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Plan next steps collaboratively with an engineer after reviewing their work.
    """
    started = time.perf_counter()
    store = await get_org_store(graph_name)

    # Get the engineer's profile
    person = await get_person(store, engineer)
    skills = (person or {}).get("skills") or []
    commitments = [
        f.get("value") for f in (person or {}).get("facts") or []
        if f.get("fact_kind") == "commitment"
    ][:5]

    # Get project state
    from kgmemory.state.repository import latest_project_states
    states = await latest_project_states(store)
    project_state = "\n".join(
        f"- {s.get('project')}: {s.get('health')}, {s.get('summary')}"
        for s in states[:3]
    ) or "No project states available."

    # Get available tasks
    tasks = await list_tasks(store)
    available_tasks = [
        {"title": t["title"], "project": t["project"], "skills": t.get("required_skills") or []}
        for t in tasks
        if t["status"] == "open"
    ][:5]

    review_summary = (
        f"Assessment: {review.get('assessment', 'unknown')}\n"
        f"What was done: {review.get('what_was_done', 'unknown')}\n"
        f"What's missing: {review.get('what_is_missing', 'nothing noted')}\n"
        f"Confidence: {review.get('confidence_in_claim', 0.5)}"
    )

    prompt = NEXT_STEPS_PROMPT.format(
        engineer=engineer,
        review=review_summary,
        commitments="\n".join(commitments) or "No open commitments",
        skills=", ".join(skills) or "No skills recorded",
        project_state=project_state,
        available_tasks=str(available_tasks) if available_tasks else "No open tasks",
    )

    try:
        response = await get_llm().complete(prompt, kind="planning", max_tokens=1000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Next steps payload is not an object")
    except Exception as exc:
        logger.exception(f"Next steps LLM failed: {exc}")
        payload = {
            "message_to_engineer": "Thanks for the update. Let's figure out what's next.",
            "suggested_next_tasks": [],
            "expectations": ["Please provide more details on your current work"],
            "tone": "neutral",
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["engineer"] = engineer
    payload["elapsed_ms"] = elapsed
    return payload


def _extract_evidence(claim: str) -> str:
    """Extract evidence signals from a claim string."""
    evidence_signals = []
    claim_lower = claim.lower()

    # PR numbers
    if "pr #" in claim_lower or "pull request" in claim_lower:
        evidence_signals.append("Mentions PR/pull request")
    # Deployments
    if "deploy" in claim_lower or "shipped" in claim_lower or "live" in claim_lower:
        evidence_signals.append("Mentions deployment/shipping")
    # Tests
    if "test" in claim_lower:
        evidence_signals.append("Mentions tests")
    # Numbers
    if any(c.isdigit() for c in claim):
        evidence_signals.append("Contains specific numbers")
    # URLs
    if "http" in claim_lower:
        evidence_signals.append("Contains URL")

    if not evidence_signals:
        return "No concrete evidence detected — claim is verbal only"
    return "; ".join(evidence_signals)
