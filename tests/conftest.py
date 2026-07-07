import os

# Provide defaults before any kgmemory module is imported.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URI", "postgres://postgres:postgres@localhost:5432/kgmemory_test")
os.environ.setdefault("DEFAULT_FROM_EMAIL", "noreply@example.com")
os.environ.setdefault("FIRST_SUPERUSER_EMAIL", "admin@example.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "testpassword123")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
