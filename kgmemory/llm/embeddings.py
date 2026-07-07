from __future__ import annotations

from openai import AsyncOpenAI

from kgmemory.core.config import settings


class EmbeddingClient:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=str(settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL),
            api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        self.dimensions = settings.EMBEDDING_DIMENSIONS

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in response.data]


_client: EmbeddingClient | None = None


def get_embedder() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
