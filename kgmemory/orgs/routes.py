from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from tortoise.exceptions import IntegrityError

from kgmemory.core.auth import current_user
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


async def _owned_org(org_id: UUID, user: User) -> Organization:
    org = await Organization.get_or_none(id=org_id, owner=user)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.post("/", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_org(payload: OrganizationCreate, user: User = Depends(current_user)):
    try:
        return await Organization.create(owner=user, **payload.model_dump())
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken") from exc


@router.get("/", response_model=list[OrganizationRead])
async def list_orgs(user: User = Depends(current_user)):
    return await Organization.filter(owner=user)


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_org(org_id: UUID, user: User = Depends(current_user)):
    return await _owned_org(org_id, user)


@router.post(
    "/{org_id}/api-keys",
    response_model=APIKeyCreated,
    status_code=status.HTTP_201_CREATED,
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


@router.get("/{org_id}/api-keys", response_model=list[APIKeyRead])
async def list_api_keys(org_id: UUID, user: User = Depends(current_user)):
    org = await _owned_org(org_id, user)
    return await OrgAPIKey.filter(organization=org)


@router.delete("/{org_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(org_id: UUID, key_id: UUID, user: User = Depends(current_user)):
    org = await _owned_org(org_id, user)
    key = await OrgAPIKey.get_or_none(id=key_id, organization=org)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    key.is_active = False
    await key.save(update_fields=["is_active"])
