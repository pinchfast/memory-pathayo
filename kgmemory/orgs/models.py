from __future__ import annotations

import hashlib
import secrets

from tortoise import fields

from kgmemory.db.models import TimeStampedModel


class Organization(TimeStampedModel):
    id = fields.UUIDField(pk=True)
    name = fields.CharField(max_length=255)
    slug = fields.CharField(max_length=64, unique=True)
    owner = fields.ForeignKeyField("models.User", related_name="organizations")
    is_active = fields.BooleanField(default=True)
    preferred_language = fields.CharField(max_length=16, default="en")
    slack_team_id = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "organizations"

    def __str__(self) -> str:
        return self.slug

    @property
    def graph_name(self) -> str:
        from kgmemory.core.config import settings

        return f"{settings.GRAPH_NAME_PREFIX}_{self.id.hex}"


class OrgAPIKey(TimeStampedModel):
    id = fields.UUIDField(pk=True)
    organization = fields.ForeignKeyField("models.Organization", related_name="api_keys")
    name = fields.CharField(max_length=255)
    prefix = fields.CharField(max_length=12, index=True)
    key_hash = fields.CharField(max_length=64, unique=True)
    is_active = fields.BooleanField(default=True)
    last_used_at = fields.DatetimeField(null=True)

    class Meta:
        table = "org_api_keys"

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    @staticmethod
    def generate() -> tuple[str, str, str]:
        raw = f"pfm_{secrets.token_urlsafe(32)}"
        return raw, raw[:12], OrgAPIKey.hash_key(raw)

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()
