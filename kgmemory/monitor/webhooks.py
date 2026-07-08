"""Webhook delivery for alerts.

When an alert is created, if the org has a webhook_url configured, we POST
the alert payload to that URL with an HMAC signature header so the backend
can verify authenticity. Fire-and-forget with retry.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from kgmemory.core.logger import logger
from kgmemory.orgs.models import Organization


async def dispatch_alert_webhook(org: Organization, alert: dict[str, Any]) -> None:
    """POST an alert to the org's webhook URL, if configured."""
    if not org.webhook_url:
        return

    payload = json.dumps({"event": "alert", "org_slug": org.slug, "alert": alert})
    secret = org.webhook_secret or ""

    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-PinchFast-Event": "alert",
        "X-PinchFast-Signature": f"sha256={signature}",
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(org.webhook_url, content=payload, headers=headers)
                if resp.status_code < 400:
                    logger.info(
                        f"Webhook delivered to {org.webhook_url} for alert {alert.get('alert_id')}"
                    )
                    return
                logger.warning(
                    f"Webhook returned {resp.status_code} (attempt {attempt + 1}): {resp.text[:200]}"
                )
        except Exception as exc:
            logger.warning(f"Webhook delivery failed (attempt {attempt + 1}): {exc}")
        if attempt < 2:
            await asyncio.sleep(2**attempt)

    logger.error(f"Webhook delivery failed after 3 attempts for alert {alert.get('alert_id')}")


async def dispatch_alert_webhook_safe(org: Organization, alert: dict[str, Any]) -> None:
    """Fire-and-forget wrapper that never raises."""
    try:
        await dispatch_alert_webhook(org, alert)
    except Exception:
        logger.exception("Webhook dispatch failed unexpectedly")
