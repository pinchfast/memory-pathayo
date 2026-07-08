from __future__ import annotations

import asyncio

from openai import APIError, AsyncOpenAI

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.core.metrics import LLM_CALLS, LLM_TOKENS


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=str(settings.LLM_BASE_URL),
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        self._current_org_id: str | None = None

    def set_org_context(self, org_id: str | None) -> None:
        """Set the current org for per-org token tracking."""
        self._current_org_id = org_id

    async def complete(
        self,
        prompt: str,
        *,
        kind: str = "general",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                    temperature=(
                        temperature
                        if temperature is not None
                        else settings.LLM_TEMPERATURE
                    ),
                )
                choice = response.choices[0]
                content = (choice.message.content or "").strip()
                if not content or choice.finish_reason == "content_filter":
                    raise LLMError(f"Empty or filtered response (finish={choice.finish_reason})")
                LLM_CALLS.labels(kind, "success").inc()
                # Track token usage
                if response.usage:
                    LLM_TOKENS.labels(kind, "input").inc(response.usage.prompt_tokens)
                    LLM_TOKENS.labels(kind, "output").inc(response.usage.completion_tokens)
                    await _track_org_tokens(response.usage.total_tokens)
                return content
            except (APIError, LLMError, asyncio.TimeoutError) as exc:
                last_error = exc
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {exc}")
                if attempt < settings.LLM_MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
        LLM_CALLS.labels(kind, "failure").inc()
        raise LLMError(f"LLM call failed after retries: {last_error}") from last_error


async def _track_org_tokens(tokens: int) -> None:
    """Track token usage against the org's monthly quota."""
    from kgmemory.orgs.models import Organization

    if LLMClient_instance._current_org_id is None:
        return
    try:
        org = await Organization.get_or_none(id=LLMClient_instance._current_org_id)
        if org:
            org.tokens_used_this_month += tokens
            await org.save(update_fields=["tokens_used_this_month"])
    except Exception:
        logger.debug("Token tracking failed (DB not ready or no org context)")


LLMClient_instance: LLMClient | None = None


def get_llm() -> LLMClient:
    global LLMClient_instance
    if LLMClient_instance is None:
        LLMClient_instance = LLMClient()
    return LLMClient_instance
