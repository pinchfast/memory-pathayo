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


async def start_project_intake(
    graph_name: str, founder: str, project_name: str | None = None
) -> dict[str, Any]:
    """Start the project intake conversation with a founder."""
    known_info = "New project — no information yet."
    if project_name:
        known_info = f"Project name: {project_name}"

    result = await _generate_intake_response(
        graph_name, founder, "vision", conversation="", known_info=known_info
    )
    result["founder"] = founder
    result["step"] = "vision"
    return result


async def continue_project_intake(
    graph_name: str,
    founder: str,
    message: str,
    current_step: str,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Continue the project intake conversation. The founder has responded —
    we ingest their response, extract facts, and generate the next question.
    """
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

    # Check if we can extract a project name from the conversation
    store = await get_org_store(graph_name)
    projects = await list_projects(store)
    known_projects = [p["name"] for p in projects]

    # Build known info from existing projects
    if project_name:
        known_info = f"Project: {project_name}"
    elif known_projects:
        known_info = f"Known projects: {', '.join(known_projects)}"
    else:
        known_info = "No project created yet."

    next_step = _next_step(current_step)

    result = await _generate_intake_response(
        graph_name, founder, next_step, conversation=message, known_info=known_info
    )
    result["founder"] = founder
    result["step"] = result.get("next_step", next_step)

    # If the LLM extracted a project name, create the project
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

    return result


async def _generate_intake_response(
    graph_name: str,
    founder: str,
    step: str,
    conversation: str,
    known_info: str,
) -> dict[str, Any]:
    """Generate the next intake message using the LLM."""
    prompt = PROJECT_INTAKE_PROMPT.format(
        founder=founder,
        known_info=known_info,
        conversation=conversation or "(start of conversation)",
        step=step,
    )

    try:
        response = await get_llm().complete(prompt, kind="intake", max_tokens=800)
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
