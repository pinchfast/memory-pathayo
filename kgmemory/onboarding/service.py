"""Engineer onboarding conversation flow.

The PM has a structured conversation with each new engineer to learn about
their skills, experience, availability, and interests. The conversation
progresses through steps, extracting facts at each stage.
"""
from __future__ import annotations

from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import ENGINEER_ONBOARDING_PROMPT
from kgmemory.memory.ingest import ingest_message
from kgmemory.people.service import get_person, upsert_person

ONBOARDING_STEPS = [
    "role_experience",
    "skills",
    "past_projects",
    "availability",
    "interests",
    "work_style",
    "done",
]


async def start_onboarding(
    graph_name: str, name: str, role: str = "engineer"
) -> dict[str, Any]:
    """Start the onboarding conversation for a new engineer.
    Creates the person profile if they don't exist, then returns the first question.
    """
    store = await get_org_store(graph_name)
    # Create or update the person profile
    await upsert_person(
        store,
        {
            "name": name,
            "role": role,
            "title": None,
            "skills": [],
            "languages": [],
            "is_technical": role in ("engineer", "designer"),
        },
    )
    # Store the onboarding step on the Person node
    await store.query(
        "MATCH (p:Person) WHERE toLower(p.name) = $name "
        "SET p.onboarding_step = 'role_experience'",
        {"name": name.strip().lower()},
    )

    # Generate the first question
    result = await _generate_onboarding_response(
        graph_name, name, "role_experience", conversation="", known_info="New engineer — no information yet."
    )
    result["person"] = name
    result["step"] = "role_experience"
    return result


async def continue_onboarding(
    graph_name: str, name: str, message: str, current_step: str
) -> dict[str, Any]:
    """Continue the onboarding conversation. The engineer has responded to the
    last question — we ingest their response, extract facts, and let the LLM
    decide whether to advance to the next step or push back on their answer.
    """
    # Ingest the engineer's response as a conversation to extract facts
    from kgmemory.memory.schemas import IngestRequest
    await ingest_message(
        graph_name,
        IngestRequest(
            channel="onboarding",
            speaker=name,
            speaker_role="engineer",
            message=message,
            project=None,
        ),
    )

    # Get what we know about this person so far
    store = await get_org_store(graph_name)
    person = await get_person(store, name)
    known_info = _format_known_info(person) if person else "No information yet."

    # Build conversation history from recent facts
    conversation = _format_conversation(person) if person else message

    # The engineer just said this — pass it explicitly so the LLM can react
    # to it without having to parse it out of the conversation history.
    # Also pass the list of steps already covered so the LLM doesn't re-ask.
    covered_steps = _get_covered_steps(current_step)
    result = await _generate_onboarding_response(
        graph_name, name, current_step,
        conversation=conversation, known_info=known_info,
        engineer_message=message,
        covered_steps=covered_steps,
    )
    actual_next_step = result.get("next_step", current_step)
    # Don't allow going backwards — if the LLM returns a step we already
    # covered, force it forward to the current step's next
    if actual_next_step in covered_steps and actual_next_step != current_step:
        actual_next_step = _next_step(current_step)
    # Store the step on the Person node so we don't lose track
    await store.query(
        "MATCH (p:Person) WHERE toLower(p.name) = $name "
        "SET p.onboarding_step = $step",
        {"name": name.strip().lower(), "step": actual_next_step},
    )
    result["person"] = name
    result["step"] = actual_next_step
    return result


async def get_onboarding_status(graph_name: str, name: str) -> dict[str, Any]:
    """Check how far along an engineer is in the onboarding process."""
    store = await get_org_store(graph_name)
    person = await get_person(store, name)
    if not person:
        return {"person": name, "started": False, "step": "not_started", "completed": False}

    # Read the stored onboarding step from the Person node
    rows = await store.query(
        "MATCH (p:Person) WHERE toLower(p.name) = $name "
        "RETURN p.onboarding_step",
        {"name": name.strip().lower()},
    )
    stored_step = rows[0][0] if rows and rows[0] else None

    facts = person.get("facts") or []
    has_skills = any(f.get("fact_kind") == "skill" for f in facts)
    has_availability = any(f.get("fact_kind") == "availability" for f in facts)
    has_preferences = any(f.get("fact_kind") == "preference" for f in facts)

    # Use the stored step if available, otherwise fall back to fact inference
    if stored_step:
        step = stored_step
        completed = step == "done"
    elif has_skills and has_availability and has_preferences:
        step = "done"
        completed = True
    elif has_skills and has_availability:
        step = "interests"
        completed = False
    elif has_skills:
        step = "availability"
        completed = False
    else:
        step = "role_experience"
        completed = False

    return {
        "person": name,
        "started": True,
        "step": step,
        "completed": completed,
        "skills_known": has_skills,
        "availability_known": has_availability,
        "preferences_known": has_preferences,
        "fact_count": len(facts),
    }


async def _generate_onboarding_response(
    graph_name: str,
    name: str,
    step: str,
    conversation: str,
    known_info: str,
    engineer_message: str = "",
    covered_steps: list[str] | None = None,
) -> dict[str, Any]:
    """Generate the next onboarding message using the LLM."""
    prompt = ENGINEER_ONBOARDING_PROMPT.format(
        name=name,
        known_info=known_info,
        conversation=conversation or "(start of conversation)",
        step=step,
        engineer_message=engineer_message or "(no message yet — this is the first question)",
        covered_steps=", ".join(covered_steps) if covered_steps else "none",
    )

    try:
        response = await get_llm().complete(prompt, kind="onboarding", max_tokens=2000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Onboarding payload is not an object")
    except Exception as exc:
        logger.exception(f"Onboarding LLM failed: {exc}")
        # Fallback: use a simple question for the current step (no greeting)
        fallback_questions = {
            "role_experience": "What's your current role and how many years of experience?",
            "skills": "What technologies and tools are you most proficient in?",
            "past_projects": "Tell me about a recent project you worked on.",
            "availability": "How many hours per week can you commit, and what's your timezone?",
            "interests": "What kind of work excites you most?",
            "work_style": "How do you prefer to communicate and handle blockers?",
            "done": f"Got it, thanks {name}. That's all I needed.",
        }
        payload = {
            "next_step": step,
            "message": fallback_questions.get(step, "Can you tell me more about that?"),
            "extracted_facts": [],
        }

    return {
        "message": payload.get("message", ""),
        "next_step": payload.get("next_step", step),
        "extracted_facts": payload.get("extracted_facts") or [],
    }


def _next_step(current_step: str) -> str:
    """Get the next step in the onboarding flow."""
    if current_step in ONBOARDING_STEPS:
        idx = ONBOARDING_STEPS.index(current_step)
        if idx + 1 < len(ONBOARDING_STEPS):
            return ONBOARDING_STEPS[idx + 1]
    return "done"


def _get_covered_steps(current_step: str) -> list[str]:
    """Get all steps that have been completed before the current step."""
    if current_step in ONBOARDING_STEPS:
        idx = ONBOARDING_STEPS.index(current_step)
        return ONBOARDING_STEPS[:idx]
    return []


def _format_known_info(person: dict[str, Any]) -> str:
    """Format what we know about a person for the LLM prompt."""
    parts = []
    if person.get("role"):
        parts.append(f"Role: {person['role']}")
    if person.get("title"):
        parts.append(f"Title: {person['title']}")
    if person.get("skills"):
        parts.append(f"Skills: {', '.join(person['skills'])}")
    if person.get("languages"):
        parts.append(f"Languages: {', '.join(person['languages'])}")
    facts = person.get("facts") or []
    if facts:
        recent = facts[:10]
        for f in recent:
            parts.append(f"- {f.get('fact_kind')}: {f.get('subject')} {f.get('predicate')} {f.get('value')}")
    return "\n".join(parts) if parts else "No information yet."


def _format_conversation(person: dict[str, Any]) -> str:
    """Format what the engineer has told us so far as conversation context.

    This gives the LLM enough context to know what's already been covered
    so it doesn't repeat questions and can react to what was said.
    """
    facts = person.get("facts") or []
    if not facts:
        return "(start of conversation)"
    lines = []
    # Show facts in reverse chronological order (most recent first)
    for f in facts[:20]:
        predicate = f.get("predicate", "")
        value = f.get("value", "")
        kind = f.get("fact_kind", "fact")
        lines.append(f"- [{kind}] {predicate}: {value}")
    return "\n".join(lines) if lines else "(start of conversation)"
