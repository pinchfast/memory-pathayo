from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from kgmemory.core.redis import get_redis
from kgmemory.graph.client import get_org_store
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import REPORT_PROMPT
from kgmemory.memory.repository import FactRepository

from .schemas import ReportRequest

STATUS_TTL_SECONDS = 7200


def status_key(report_id: str) -> str:
    return f"report:status:{report_id}"


async def set_status(
    report_id: str, status: str, *, report: dict | None = None, error: str | None = None
) -> None:
    payload = {"report_id": report_id, "status": status, "report": report, "error": error}
    await get_redis().set(status_key(report_id), json.dumps(payload), ex=STATUS_TTL_SECONDS)


async def get_status(report_id: str) -> dict | None:
    raw = await get_redis().get(status_key(report_id))
    return json.loads(raw) if raw else None


def _group_facts(facts: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for fact in facts:
        key = fact.get("fact_kind") or "fact"
        line = f"- [{fact.get('valid_from', '')[:10]}] {fact['subject']} {fact['predicate']} {fact['value']}"
        grouped[key].append(line)
    return "\n".join(f"## {kind}\n" + "\n".join(lines) for kind, lines in grouped.items())


def _build_summary(people: list[dict], projects: list[dict]) -> str:
    people_lines = [
        f"- {p['name']} ({p['role']}): reliability={p['reliability_score']}, "
        f"commitments={p['commitments']}, completed={p['completed']}, flagged={p['missed_or_flagged']}"
        for p in people
    ]
    project_lines = [
        f"- {p['name']} [{p['status']}]: {p['open_task_count']} open / {p['task_count']} total tasks"
        for p in projects
    ]
    return "People:\n" + "\n".join(people_lines) + "\n\nProjects:\n" + "\n".join(project_lines)


async def generate_report(graph_name: str, request: ReportRequest) -> dict[str, Any]:
    store = await get_org_store(graph_name)
    repo = FactRepository(store)
    facts = await repo.list_facts(
        project=request.project, current_only=True, limit=300
    )
    from kgmemory.people.service import list_people
    from kgmemory.projects.service import list_projects

    people = await list_people(store)
    projects = await list_projects(store)
    summary = _build_summary(people, projects)
    grouped = _group_facts(facts)

    prompt = REPORT_PROMPT.format(
        report_type=request.report_type,
        language=request.language,
        facts=grouped,
        summary=summary,
    )
    response = await get_llm().complete(prompt, kind="report", max_tokens=2500)
    payload = parse_json_response(response)
    if not isinstance(payload, dict):
        raise LLMError("Report payload is not an object")
    return payload
