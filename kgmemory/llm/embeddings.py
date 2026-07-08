from __future__ import annotations

import hashlib
import struct

from openai import APIError, AsyncOpenAI

from kgmemory.core.config import settings
from kgmemory.core.logger import logger


class EmbeddingClient:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=str(settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL),
            api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        self.dimensions = settings.EMBEDDING_DIMENSIONS
        self._fallback_active = False

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._fallback_active:
            return [self._hash_embedding(t) for t in texts]
        try:
            response = await self._client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
                dimensions=self.dimensions,
            )
            return [item.embedding for item in response.data]
        except (APIError, Exception) as exc:
            logger.warning(f"Embedding API failed, switching to fallback: {exc}")
            self._fallback_active = True
            return [self._hash_embedding(t) for t in texts]

    def _hash_embedding(self, text: str) -> list[float]:
        """Deterministic hash-based fallback embedding.

        This is NOT semantically meaningful — it only preserves identity
        (same text → same vector) so dedup still works. Vector search quality
        will be degraded, but ingest won't fail. The system self-heals when
        the API comes back (next process restart resets _fallback_active).
        """
        digest = hashlib.sha512(text.encode()).digest()
        # Expand the 64-byte digest into N floats by chunking
        floats: list[float] = []
        for i in range(0, len(digest), 4):
            chunk = digest[i : i + 4]
            if len(chunk) < 4:
                chunk = chunk + b"\x00" * (4 - len(chunk))
            val = struct.unpack("<I", chunk)[0]
            floats.append((val / 4294967295.0) * 2 - 1)  # normalize to [-1, 1]
        # Pad or truncate to desired dimensions
        while len(floats) < self.dimensions:
            floats.append(0.0)
        return floats[: self.dimensions]


_client: EmbeddingClient | None = None


def get_embedder() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
