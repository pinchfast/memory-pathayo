from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "users" (
    "email" VARCHAR(255) NOT NULL UNIQUE,
    "hashed_password" VARCHAR(1024) NOT NULL,
    "is_active" BOOL NOT NULL DEFAULT True,
    "is_superuser" BOOL NOT NULL DEFAULT False,
    "is_verified" BOOL NOT NULL DEFAULT False,
    "id" UUID NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "short_name" VARCHAR(255),
    "full_name" VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS "idx_users_email_133a6f" ON "users" ("email");
CREATE TABLE IF NOT EXISTS "organizations" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" UUID NOT NULL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "slug" VARCHAR(64) NOT NULL UNIQUE,
    "is_active" BOOL NOT NULL DEFAULT True,
    "preferred_language" VARCHAR(16) NOT NULL DEFAULT 'en',
    "slack_team_id" VARCHAR(64),
    "webhook_url" VARCHAR(500),
    "webhook_secret" VARCHAR(128),
    "report_schedule" VARCHAR(16) NOT NULL DEFAULT 'none',
    "report_email" VARCHAR(255),
    "monthly_token_quota" INT NOT NULL DEFAULT 500000,
    "tokens_used_this_month" INT NOT NULL DEFAULT 0,
    "owner_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "org_api_keys" (
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "id" UUID NOT NULL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "prefix" VARCHAR(12) NOT NULL,
    "key_hash" VARCHAR(64) NOT NULL UNIQUE,
    "is_active" BOOL NOT NULL DEFAULT True,
    "last_used_at" TIMESTAMPTZ,
    "organization_id" UUID NOT NULL REFERENCES "organizations" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_org_api_key_prefix_31b4df" ON "org_api_keys" ("prefix");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
)
