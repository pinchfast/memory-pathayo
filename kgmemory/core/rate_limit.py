from fastapi import HTTPException, status

from .config import settings
from .redis import get_redis


async def enforce_rate_limit(identifier: str) -> None:
    redis = get_redis()
    key = f"ratelimit:{identifier}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)
    if current > settings.RATE_LIMIT_REQUESTS:
        ttl = await redis.ttl(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(ttl, 1))},
        )
