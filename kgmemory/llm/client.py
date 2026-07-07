from __future__ import annotations

import asyncio

from openai import APIError, AsyncOpenAI

from kgmemory.core.config import settings
from kgmemory.core.logger import logger
from kgmemory.core.metrics import LLM_CALLS


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=str(settings.LLM_BASE_URL),
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

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
                return content
            except (APIError, LLMError, asyncio.TimeoutError) as exc:
                last_error = exc
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {exc}")
                if attempt < settings.LLM_MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
        LLM_CALLS.labels(kind, "failure").inc()
        raise LLMError(f"LLM call failed after retries: {last_error}") from last_error


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
