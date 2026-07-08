"""SAQ task for the periodic monitor loop + scheduled task registration."""
from __future__ import annotations

from kgmemory.core.logger import logger
from kgmemory.orgs.models import Organization

from .monitor import escalate_stale_alerts, run_monitor_loop


async def monitor_all_orgs(_: dict) -> dict:
    """SAQ task: scan every active org's graph for time-based risks.

    Registered as a SAQ cron schedule so it runs every MONITOR_INTERVAL_MINUTES.
    """
    orgs = await Organization.filter(is_active=True)
    results = []
    for org in orgs:
        try:
            result = await run_monitor_loop(org.graph_name, org=org)
            results.append(result)
        except Exception:
            logger.exception(f"Monitor loop failed for org {org.slug}")
    total_alerts = sum(r["alerts_generated"] for r in results)
    logger.info(f"Monitor sweep complete: {len(results)} orgs, {total_alerts} alerts")
    return {"orgs_scanned": len(results), "total_alerts": total_alerts, "results": results}


async def escalate_all_orgs(_: dict) -> dict:
    """SAQ task: escalate unacknowledged alerts past the 24h threshold."""
    orgs = await Organization.filter(is_active=True)
    results = []
    for org in orgs:
        try:
            result = await escalate_stale_alerts(org.graph_name, org=org)
            results.append(result)
        except Exception:
            logger.exception(f"Escalation failed for org {org.slug}")
    total = sum(r["escalated_count"] for r in results)
    logger.info(f"Escalation sweep complete: {len(results)} orgs, {total} escalated")
    return {"orgs_scanned": len(results), "total_escalated": total, "results": results}


# SAQ cron schedule
MONITOR_SCHEDULE = {
    "monitor_all_orgs": {
        "function": monitor_all_orgs,
        "cron": "*/15 * * * *",  # every 15 minutes
    },
    "escalate_all_orgs": {
        "function": escalate_all_orgs,
        "cron": "0 */6 * * *",  # every 6 hours
    },
}
