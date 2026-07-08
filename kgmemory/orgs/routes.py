from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from tortoise.exceptions import IntegrityError

from kgmemory.core.auth import current_user
from kgmemory.core.openapi import ERROR_RESPONSES
from kgmemory.users.models import User

from .models import Organization, OrgAPIKey
from .schemas import (
    APIKeyCreate,
    APIKeyCreated,
    APIKeyRead,
    OrganizationCreate,
    OrganizationRead,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])

API_KEY_RESPONSE_EXAMPLE = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Production",
    "prefix": "pfm_a1b2c3",
    "is_active": True,
    "last_used_at": None,
    "created_at": "2026-07-08T10:00:00Z",
    "key": "pfm_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
}


async def _owned_org(org_id: UUID, user: User) -> Organization:
    org = await Organization.get_or_none(id=org_id, owner=user)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.post(
    "/",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
    description="Create a new SaaS organization. Each org gets its own isolated knowledge graph. Requires JWT auth.",
    responses={
        **ERROR_RESPONSES,
        409: {"description": "Slug already taken"},
    },
)
async def create_org(payload: OrganizationCreate, user: User = Depends(current_user)):
    try:
        return await Organization.create(owner=user, **payload.model_dump())
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Slug already taken"
        ) from exc


@router.get(
    "/",
    response_model=list[OrganizationRead],
    summary="List your organizations",
    description="List all organizations owned by the authenticated user.",
)
async def list_orgs(user: User = Depends(current_user)):
    return await Organization.filter(owner=user)


@router.get(
    "/{org_id}",
    response_model=OrganizationRead,
    summary="Get an organization",
    description="Get details of a specific organization you own.",
    responses={**ERROR_RESPONSES, 404: {"description": "Organization not found"}},
)
async def get_org(org_id: UUID, user: User = Depends(current_user)):
    return await _owned_org(org_id, user)


@router.post(
    "/{org_id}/api-keys",
    response_model=APIKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description=(
        "Generate a new API key for an organization. **The raw key is shown only "
        "once** — store it securely. Use it as the `X-API-Key` header for all "
        "memory, context, people, projects, reports, and PM-brain endpoints."
    ),
    responses={
        **ERROR_RESPONSES,
        201: {
            "description": "API key created (raw key shown only once)",
            "content": {"application/json": {"example": API_KEY_RESPONSE_EXAMPLE}},
        },
    },
)
async def create_api_key(
    org_id: UUID, payload: APIKeyCreate, user: User = Depends(current_user)
):
    org = await _owned_org(org_id, user)
    raw, prefix, key_hash = OrgAPIKey.generate()
    record = await OrgAPIKey.create(
        organization=org, name=payload.name, prefix=prefix, key_hash=key_hash
    )
    return APIKeyCreated(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        is_active=record.is_active,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
        key=raw,
    )


@router.get(
    "/{org_id}/api-keys",
    response_model=list[APIKeyRead],
    summary="List API keys",
    description="List all API keys for an organization. Raw keys are never shown — only the prefix.",
    responses=ERROR_RESPONSES,
)
async def list_api_keys(org_id: UUID, user: User = Depends(current_user)):
    org = await _owned_org(org_id, user)
    return await OrgAPIKey.filter(organization=org)


@router.delete(
    "/{org_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description="Deactivate an API key. It will no longer be accepted on protected endpoints.",
    responses={**ERROR_RESPONSES, 204: {"description": "Key revoked"}},
)
async def revoke_api_key(org_id: UUID, key_id: UUID, user: User = Depends(current_user)):
    org = await _owned_org(org_id, user)
    key = await OrgAPIKey.get_or_none(id=key_id, organization=org)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    key.is_active = False
    await key.save(update_fields=["is_active"])
