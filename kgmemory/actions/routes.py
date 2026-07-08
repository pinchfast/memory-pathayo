from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.graph.client import get_org_store
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization

from .repository import complete_action, list_actions

router = APIRouter(prefix="/actions", tags=["monitor"])

ACTION_EXAMPLE = {
    "action_id": "action:2026-07-08T12:00:00:0:ping:dave",
    "action": "ping",
    "target": "dave",
    "message": "Hey Dave, any update on the auth module? It's past the Friday deadline.",
    "urgency": "high",
    "status": "pending",
    "created_at": "2026-07-08T12:00:00+00:00",
    "completed_at": None,
}


@router.get(
    "",
    summary="List pending actions",
    description=(
        "List actions suggested by the PM brain (`/pm/decide`) that haven't been "
        "executed yet. The Django backend polls this endpoint to know what to do "
        "(send Slack pings, escalate, reassign, warn founders). Filter by status: "
        "`pending` (default), `completed`, or `all`."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "List of actions",
            "content": {"application/json": {"example": [ACTION_EXAMPLE]}},
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def list_actions_endpoint(
    action_status: str = Query("pending", pattern="^(pending|completed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    org: Organization = Depends(get_current_org),
):
    store = await get_org_store(org.graph_name)
    return await list_actions(store, status=action_status, limit=limit)


@router.post(
    "/{action_id}/complete",
    summary="Mark an action as completed",
    description=(
        "Mark a suggested action as completed. Called by the Django backend after "
        "it executes the action (e.g. after sending the Slack ping). Completed "
        "actions won't appear in the pending list."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        200: {
            "description": "Action completed",
            "content": {
                "application/json": {
                    "example": {
                        "action_id": "action:2026-07-08T12:00:00:0:ping:dave",
                        "status": "completed",
                        "completed_at": "2026-07-08T13:00:00+00:00",
                    }
                }
            },
        },
        404: {"description": "Action not found or already completed"},
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def complete_action_endpoint(
    action_id: str, org: Organization = Depends(get_current_org)
):
    store = await get_org_store(org.graph_name)
    result = await complete_action(store, action_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found or already completed",
        )
    return result
