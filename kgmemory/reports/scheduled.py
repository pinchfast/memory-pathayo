"""Scheduled report generation.

A SAQ cron task that runs daily, checks which orgs have report schedules
configured (daily/weekly), generates their reports, and emails them if
an email address is configured.
"""
from __future__ import annotations

from datetime import datetime, timezone

from kgmemory.core.logger import logger
from kgmemory.orgs.models import Organization
from kgmemory.reports.schemas import ReportRequest
from kgmemory.reports.service import generate_report


async def generate_scheduled_reports(_: dict) -> dict:
    """SAQ task: generate scheduled reports for all orgs that have them configured.

    Runs daily at 9 AM UTC. For orgs with `report_schedule='daily'`, generates
    a daily report every day. For `report_schedule='weekly'`, generates on Mondays.
    """
    now = datetime.now(timezone.utc)
    is_monday = now.weekday() == 0

    orgs = await Organization.filter(is_active=True)
    generated: list[dict] = []

    for org in orgs:
        schedule = (org.report_schedule or "none").lower()
        if schedule == "none":
            continue
        if schedule == "weekly" and not is_monday:
            continue
        if schedule not in ("daily", "weekly"):
            continue

        try:
            report = await generate_report(
                org.graph_name,
                ReportRequest(
                    report_type="weekly" if schedule == "weekly" else "status",
                    language=org.preferred_language,
                ),
            )
            generated.append({
                "org_slug": org.slug,
                "report_title": report.get("title", ""),
                "risk_level": report.get("risk_level", ""),
            })

            if org.report_email:
                await _email_report(org, report)

        except Exception:
            logger.exception(f"Scheduled report failed for org {org.slug}")

    logger.info(f"Scheduled reports: {len(generated)} generated")
    return {"reports_generated": len(generated), "reports": generated}


async def _email_report(org: Organization, report: dict) -> None:
    """Send a report via email. Uses the email service if configured."""
    try:
        from kgmemory.services.email import send_email_task

        await send_email_task.kiq(
            to=org.report_email,
            subject=f"[PinchFast] {report.get('title', 'Weekly Report')}",
            body=report.get("body_markdown", ""),
        )
    except Exception:
        logger.exception(f"Failed to email report to {org.report_email}")


SCHEDULED_REPORT_SCHEDULE = {
    "generate_scheduled_reports": {
        "function": generate_scheduled_reports,
        "cron": "0 9 * * *",  # daily at 9 AM UTC
    },
}
