from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from tortoise.timezone import now

from kgmemory.core.rate_limit import enforce_rate_limit

from .models import Organization, OrgAPIKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_org(api_key: str | None = Security(api_key_header)) -> Organization:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key"
        )
    record = await OrgAPIKey.get_or_none(
        key_hash=OrgAPIKey.hash_key(api_key), is_active=True
    ).prefetch_related("organization")
    if record is None or not record.organization.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    await enforce_rate_limit(str(record.organization_id))
    record.last_used_at = now()
    await record.save(update_fields=["last_used_at"])
    return record.organization


CurrentOrg = Depends(get_current_org)
