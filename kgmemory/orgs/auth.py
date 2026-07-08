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

    # Set org context for token tracking
    from kgmemory.llm.client import get_llm
    get_llm().set_org_context(str(record.organization_id))

    # Quota check
    org = record.organization
    if org.monthly_token_quota > 0 and org.tokens_used_this_month >= org.monthly_token_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly token quota exceeded ({org.tokens_used_this_month}/{org.monthly_token_quota})",
        )

    return org


CurrentOrg = Depends(get_current_org)
