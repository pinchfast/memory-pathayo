"""Founder project intake conversation flow.

The PM has a structured conversation with the founder to understand the project
deeply — vision, goals, timeline, team, constraints, and priorities.
"""
from __future__ import annotations

from typing import Any

from kgmemory.core.logger import logger
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import PROJECT_INTAKE_PROMPT
from kgmemory.memory.ingest import ingest_message

from .service import list_projects, upsert_project

INTAKE_STEPS = [
    "vision",
    "goals",
    "timeline",
    "team",
    "constraints",
    "priorities",
    "done",
]

# In-memory conversation tracking per founder (graph_name + founder)
_intake_history: dict[str, list[dict[str, str]]] = {}


def _history_key(graph_name: str, founder: str) -> str:
    return f"{graph_name}:{founder}"


async def start_project_intake(
    graph_name: str, founder: str, project_name: str | None = None
) -> dict[str, Any]:
    """Start the project intake conversation with a founder."""
    _intake_history[_history_key(graph_name, founder)] = []

    known_info = "New project — no information yet."
    if project_name:
        known_info = f"Project name: {project_name}"

    result = await _generate_intake_response(
        graph_name, founder, "vision",
        conversation="",
        known_info=known_info,
        covered_steps=[],
    )
    result["founder"] = founder
    result["step"] = "vision"

    _intake_history[_history_key(graph_name, founder)].append(
        {"role": "pm", "step": "vision", "text": result["message"]}
    )

    return result


async def continue_project_intake(
    graph_name: str,
    founder: str,
    message: str,
    current_step: str,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Continue the project intake conversation."""
    key = _history_key(graph_name, founder)
    history = _intake_history.setdefault(key, [])

    # Track founder's response
    history.append({"role": "founder", "step": current_step, "text": message})

    # Ingest the founder's response
    from kgmemory.memory.schemas import IngestRequest
    await ingest_message(
        graph_name,
        IngestRequest(
            channel="project_intake",
            speaker=founder,
            speaker_role="founder",
            message=message,
            project=project_name,
        ),
    )

    store = await get_org_store(graph_name)
    projects = await list_projects(store)
    known_projects = [p["name"] for p in projects]

    if project_name:
        known_info = f"Project: {project_name}"
    elif known_projects:
        known_info = f"Known projects: {', '.join(known_projects)}"
    else:
        known_info = "No project created yet."

    covered_steps = _get_covered_steps(current_step)
    next_step = _next_step(current_step)

    result = await _generate_intake_response(
        graph_name, founder, next_step,
        conversation=_format_history(history),
        known_info=known_info,
        covered_steps=covered_steps,
        founder_message=message,
    )
    result["founder"] = founder

    # Enforce forward-only step progression
    llm_step = result.get("next_step", next_step)
    result["step"] = _enforce_forward(current_step, llm_step, next_step)

    # Track PM's response
    history.append({"role": "pm", "step": result["step"], "text": result["message"]})

    # Create project if LLM extracted a name
    extracted_project = result.get("project_name")
    if extracted_project and extracted_project not in known_projects:
        await upsert_project(
            store,
            {
                "name": extracted_project,
                "description": None,
                "status": "planning",
                "deadline": None,
            },
        )
        result["project_created"] = extracted_project

    # At "done", try to create project from history if not already
    if result["step"] == "done" and not extracted_project:
        project_name_from_history = _extract_project_from_history(history)
        if project_name_from_history and project_name_from_history not in known_projects:
            await upsert_project(
                store,
                {
                    "name": project_name_from_history,
                    "description": _build_description_from_history(history),
                    "status": "planning",
                    "deadline": None,
                },
            )
            result["project_created"] = project_name_from_history

    return result


def _format_history(history: list[dict[str, str]]) -> str:
    """Format conversation history for the LLM prompt."""
    lines = []
    for h in history:
        if h["role"] == "founder":
            lines.append(f"Founder: {h['text']}")
        else:
            lines.append(f"PM: {h['text']}")
    return "\n".join(lines) if lines else "(start of conversation)"


def _get_covered_steps(current_step: str) -> list[str]:
    """Steps completed before the current one."""
    if current_step not in INTAKE_STEPS:
        return []
    idx = INTAKE_STEPS.index(current_step)
    return INTAKE_STEPS[:idx]


def _enforce_forward(current_step: str, llm_step: str, deterministic_next: str) -> str:
    """Never let the step go backwards."""
    if llm_step not in INTAKE_STEPS:
        return deterministic_next
    current_idx = INTAKE_STEPS.index(current_step) if current_step in INTAKE_STEPS else 0
    llm_idx = INTAKE_STEPS.index(llm_step)
    if llm_idx < current_idx:
        return deterministic_next
    if llm_idx == current_idx:
        return current_step
    return llm_step


def _extract_project_from_history(history: list[dict[str, str]]) -> str | None:
    """Try to find a project name in the conversation."""
    for h in history:
        if h["role"] == "founder":
            text = h["text"].lower()
            for pattern in ["called ", "named ", "project ", "build ", "building "]:
                if pattern in text:
                    idx = text.index(pattern) + len(pattern)
                    rest = h["text"][idx:].strip()
                    words = rest.split()[:3]
                    if words:
                        name = " ".join(words).rstrip(".,!?")
                        if len(name) > 2 and name.lower() not in ("the", "a", "an", "my", "our"):
                            return name
    return None


def _build_description_from_history(history: list[dict[str, str]]) -> str:
    """Build a project description from the first founder message."""
    for h in history:
        if h["role"] == "founder":
            return h["text"][:500]
    return None


async def _generate_intake_response(
    graph_name: str,
    founder: str,
    step: str,
    conversation: str,
    known_info: str,
    covered_steps: list[str] | None = None,
    founder_message: str | None = None,
) -> dict[str, Any]:
    """Generate the next intake message using the LLM."""
    covered = covered_steps or []
    prompt = PROJECT_INTAKE_PROMPT.format(
        founder=founder,
        known_info=known_info,
        conversation=conversation or "(start of conversation)",
        step=step,
        covered_steps=", ".join(covered) if covered else "(none yet)",
        founder_message=founder_message or "(first message)",
    )

    try:
        response = await get_llm().complete(prompt, kind="intake", max_tokens=1000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Intake payload is not an object")
    except Exception as exc:
        logger.exception(f"Project intake LLM failed: {exc}")
        fallback_questions = {
            "vision": "Tell me about the project. What are you building and why?",
            "goals": "What does success look like? What are the key milestones?",
            "timeline": "What's your target timeline? Any hard deadlines?",
            "team": "Who's on the team? What roles do you need filled?",
            "constraints": "Any constraints I should know about? Budget, tech stack, integrations?",
            "priorities": "If we can only ship one thing first, what is it?",
            "done": "Great! I've captured the project details. Let me set things up.",
        }
        payload = {
            "next_step": step,
            "message": fallback_questions.get(step, "Tell me more."),
            "extracted_facts": [],
            "project_name": None,
        }

    return {
        "message": payload.get("message", ""),
        "next_step": payload.get("next_step", step),
        "extracted_facts": payload.get("extracted_facts") or [],
        "project_name": payload.get("project_name"),
    }


def _next_step(current_step: str) -> str:
    """Get the next step in the intake flow."""
    if current_step in INTAKE_STEPS:
        idx = INTAKE_STEPS.index(current_step)
        if idx + 1 < len(INTAKE_STEPS):
            return INTAKE_STEPS[idx + 1]
    return "done"
