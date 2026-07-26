from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

TAGS_METADATA = [
    {
        "name": "pm-brain",
        "description": "The AI project manager's decision layer. **/pm/decide** synthesizes "
        "retrieved memory + current project/person states into an audience-tuned "
        "response with suggested actions (auto-queued for execution). "
        "**/pm/check-in** generates proactive check-in messages for silent or "
        "at-risk engineers. **/pm/check-in/auto** scans for everyone who needs "
        "checking in. **/pm/infer-state** manually triggers state inference "
        "(normally runs automatically after each ingest).",
    },
    {
        "name": "memory",
        "description": "Ingest conversations and manage facts. Ingestion is async — the API "
        "returns a `request_id` immediately; poll `/memory/ingest/{request_id}` for "
        "the result. Facts are extracted by the LLM, deduplicated, and stored in the "
        "org's knowledge graph with vector embeddings.",
    },
    {
        "name": "context",
        "description": "Hybrid retrieval (vector + graph traversal + LLM rerank) returning a "
        "prompt-context string plus structured facts and current project/person states. "
        "This is what the Django backend calls to give the PM agent its memory.",
    },
    {
        "name": "people",
        "description": "Team member profiles with skills, experience, availability, interests, "
        "reliability scores, and contribution timelines. The PM uses these to make "
        "assignment decisions and track who delivers over time.",
    },
    {
        "name": "projects",
        "description": "Projects and tasks. Includes project intake conversation flow, "
        "task assignment recommendations, and autonomous PM assignment.",
    },
    {
        "name": "onboarding",
        "description": "Engineer onboarding conversation. The PM has a structured interview "
        "with each new engineer to learn about their skills, experience, availability, "
        "and interests. Facts are extracted and stored automatically.",
    },
    {
        "name": "reports",
        "description": "Async LLM-composed reports (weekly / status / risk / founder_summary) "
        "in the org's preferred language. Returns a `report_id`; poll for the result.",
    },
    {
        "name": "monitor",
        "description": "Autonomous risk monitoring. The monitor loop runs every 15 minutes "
        "via the SAQ worker, scanning for overdue commitments, engineer silence, "
        "single points of failure, and stale blockers. Alerts are stored as graph "
        "nodes — list them here, trigger a manual scan, or acknowledge resolved ones.",
    },
    {
        "name": "organizations",
        "description": "SaaS organization accounts and API key management. Each org gets its "
        "own isolated knowledge graph. API keys are SHA-256 hashed — the raw key is "
        "shown only once at creation.",
    },
    {
        "name": "auth",
        "description": "User authentication (JWT) via fastapi-users. Used for org management "
        "endpoints. Memory/context/people/projects/reports endpoints use org API keys "
        "instead (X-API-Key header).",
    },
    {
        "name": "users",
        "description": "User account management (fastapi-users).",
    },
    {
        "name": "health",
        "description": "Liveness (`/health`) and readiness (`/health/ready`) probes checking "
        "Postgres, Redis/SAQ worker, FalkorDB, LLM API, and embedding API.",
    },
    {
        "name": "sprints",
        "description": "Sprint planning, milestone tracking, retrospectives, and capacity "
        "forecasting. The PM breaks projects into timeboxed sprints, plans tasks "
        "based on team capacity, runs retrospectives, and tracks milestones.",
    },
    {
        "name": "planning",
        "description": "Scope management, dependency analysis, estimation tracking, and task "
        "prioritization. Detects scope creep, finds critical paths, tracks who "
        "underestimates, and ranks tasks by priority.",
    },
    {
        "name": "team",
        "description": "Performance feedback and team morale sensing. Generates honest, "
        "specific feedback for each engineer and detects declining morale from "
        "conversation sentiment patterns.",
    },
    {
        "name": "stakeholders",
        "description": "Stakeholder communication and budget tracking. Generates tailored "
        "updates for investors, customers, team, or board. Tracks project budget, "
        "burn rate, and runway.",
    },
]

API_KEY_SECURITY = {
    "OrgAPIKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Organization API key. Create one via `POST /orgs/{org_id}/api-keys` "
        "(requires JWT auth). The raw key starts with `pfm_` and is shown only once.",
    }
}

ERROR_RESPONSES = {
    "401": {
        "description": "Invalid or missing API key",
        "content": {
            "application/json": {
                "example": {"detail": "Missing API key"},
            }
        },
    },
    "429": {
        "description": "Rate limit exceeded (per API key)",
        "content": {
            "application/json": {
                "example": {"detail": "Rate limit exceeded", "retry_after": 42},
            }
        },
    },
    "404": {
        "description": "Resource not found",
        "content": {
            "application/json": {
                "example": {"detail": "Fact not found"},
            }
        },
    },
    "409": {
        "description": "Conflict (duplicate resource)",
        "content": {
            "application/json": {
                "example": {"detail": "Slug already taken"},
            }
        },
    },
}

ORG_PROTECTED_RESPONSES = {**ERROR_RESPONSES}


def custom_openapi(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=TAGS_METADATA,
        servers=app.servers,
    )
    schema["components"]["securitySchemes"] = API_KEY_SECURITY
    schema["info"]["contact"] = {
        "name": "PinchFast",
        "url": "https://github.com/pinchfast/memory-pinchfast",
    }
    schema["info"]["license"] = {"name": "MIT", "url": "https://opensource.org/license/mit"}
    app.openapi_schema = schema
    return schema
