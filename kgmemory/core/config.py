from __future__ import annotations

from pathlib import Path

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    PostgresDsn,
    RedisDsn,
    ValidationInfo,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class Environment(StrEnum):
    dev = "dev"
    prod = "prod"


class Paths:
    # kgmemory
    ROOT_DIR: Path = Path(__file__).parent.parent.parent
    BASE_DIR: Path = ROOT_DIR / "kgmemory"
    EMAIL_TEMPLATES_DIR: Path = BASE_DIR / "emails"
    LOGIN_PATH: str = "/auth/login"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(Paths.ROOT_DIR / ".env"))

    @property
    def PATHS(self) -> Paths:
        return Paths()

    ENVIRONMENT: Environment = "dev"
    SECRET_KEY: str
    DEBUG: bool = False
    AUTH_TOKEN_LIFETIME_SECONDS: int = 3600
    SERVER_HOST: AnyHttpUrl = "http://localhost:8000"  # type: ignore
    PAGINATION_PER_PAGE: int = 20

    REDIS_URL: RedisDsn

    BACKEND_CORS_ORIGINS: list[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, value: str | list[str]) -> list[str] | str:
        if isinstance(value, str) and not value.startswith("["):
            return [i.strip() for i in value.split(",")]
        elif isinstance(value, (list, str)):
            return value
        raise ValueError(value)

    DATABASE_URI: PostgresDsn

    # FalkorDB graph store (one graph per organization)
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379
    FALKORDB_USERNAME: str | None = None
    FALKORDB_PASSWORD: str | None = None
    GRAPH_NAME_PREFIX: str = "org"

    # OpenAI-compatible LLM
    LLM_BASE_URL: AnyHttpUrl = "https://api.openai.com/v1"  # type: ignore
    LLM_API_KEY: str = "EMPTY"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_MAX_TOKENS: int = 4000
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT_SECONDS: float = 90.0
    LLM_MAX_RETRIES: int = 2

    # OpenAI-compatible embeddings
    EMBEDDING_BASE_URL: AnyHttpUrl | None = None
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    @field_validator("EMBEDDING_BASE_URL", mode="before")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        return value or None

    # Ingestion pipeline
    INGEST_CHUNK_CHARS: int = 8000
    INGEST_MAX_MESSAGE_CHARS: int = 200_000
    INGEST_MAX_EXTRACT_CONCURRENCY: int = 4
    INGEST_DEDUP_SIMILARITY: float = 0.92

    # Context engine / retrieval
    CONTEXT_MAX_FACTS: int = 20
    CONTEXT_DENSE_TOP_K: int = 50
    CONTEXT_TRAVERSAL_MAX_HOPS: int = 3
    CONTEXT_LLM_WEIGHT: float = 0.7
    CONTEXT_DENSE_WEIGHT: float = 0.3
    CONTEXT_RECENCY_HALF_LIFE_DAYS: float = 90.0
    CONTEXT_MIN_RELEVANCE: float = 0.25

    # Rate limiting (per API key)
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    SES_ACCESS_KEY: str | None = None
    SES_SECRET_KEY: str | None = None
    SES_REGION: str | None = None
    DEFAULT_FROM_EMAIL: EmailStr
    DEFAULT_FROM_NAME: str | None = None
    EMAILS_ENABLED: bool = False

    @field_validator("EMAILS_ENABLED", mode="before")
    @classmethod
    def get_emails_enabled(cls, value: bool, info: ValidationInfo) -> bool:
        return bool(
            info.data.get("SMTP_HOST")
            and info.data.get("SMTP_PORT")
            and info.data.get("DEFAULT_FROM_EMAIL")
        )

    FIRST_SUPERUSER_EMAIL: EmailStr
    FIRST_SUPERUSER_PASSWORD: str


settings = Settings()
