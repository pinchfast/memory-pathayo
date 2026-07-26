"""Meeting summary extraction.

Ingest a meeting transcript, extract decisions, action items, blockers, and
key discussion points. Store them as facts in the knowledge graph.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from kgmemory.core.logger import logger
from kgmemory.llm.client import LLMError, get_llm
from kgmemory.llm.parsing import parse_json_response
from kgmemory.llm.prompts import MEETING_SUMMARY_PROMPT

from .ingest import ingest_message
from .schemas import IngestRequest


async def summarize_meeting(
    graph_name: str,
    transcript: str,
    participants: list[str],
    date: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Summarize a meeting transcript and extract decisions + action items."""
    started = time.perf_counter()
    meeting_date = date or datetime.now(timezone.utc).isoformat()

    prompt = MEETING_SUMMARY_PROMPT.format(
        transcript=transcript[:8000],  # Limit to avoid token overflow
        date=meeting_date[:10],
        participants=", ".join(participants) or "Unknown",
    )

    try:
        response = await get_llm().complete(prompt, kind="meeting", max_tokens=1500)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Meeting summary payload is not an object")
    except Exception as exc:
        logger.exception(f"Meeting summary LLM failed: {exc}")
        payload = {
            "summary": "Meeting summary generation failed. Transcript was ingested.",
            "decisions": [],
            "action_items": [],
            "blockers": [],
            "follow_ups": [],
            "participants": participants,
        }

    # Ingest the full transcript as a conversation so facts are extracted
    for participant in participants:
        # Try to find their lines in the transcript (simple heuristic)
        lines = [line for line in transcript.split("\n") if participant.lower() in line.lower()[:50]]
        if lines:
            await ingest_message(
                graph_name,
                IngestRequest(
                    channel="meeting",
                    speaker=participant,
                    speaker_role="engineer",
                    message=" ".join(lines[:5]),
                    project=project,
                ),
            )

    # Store decisions as facts via ingest
    for decision in payload.get("decisions") or []:
        decision_text = f"{decision.get('subject', 'company')} decided: {decision.get('value', '')}"
        await ingest_message(
            graph_name,
            IngestRequest(
                channel="meeting",
                speaker="meeting_summary",
                speaker_role="manager",
                message=decision_text,
                project=decision.get("project") or project,
            ),
        )

    # Store action items as commitment facts
    for action in payload.get("action_items") or []:
        person = action.get("person", "unknown")
        commitment_text = (
            f"{person} committed to: {action.get('commitment', '')}"
            + (f" by {action.get('due_date')}" if action.get("due_date") else "")
        )
        await ingest_message(
            graph_name,
            IngestRequest(
                channel="meeting",
                speaker=person,
                speaker_role="engineer",
                message=commitment_text,
                project=action.get("project") or project,
            ),
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["meeting_date"] = meeting_date
    payload["participants"] = payload.get("participants") or participants
    payload["elapsed_ms"] = elapsed
    return payload
