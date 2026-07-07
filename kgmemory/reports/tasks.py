from kgmemory.core.logger import logger

from .schemas import ReportRequest
from .service import generate_report, set_status


async def generate_report_task(
    _: dict, *, report_id: str, graph_name: str, payload: dict
) -> dict:
    await set_status(report_id, "running")
    try:
        report = await generate_report(graph_name, ReportRequest(**payload))
    except Exception as exc:
        logger.exception(f"Report {report_id} failed")
        await set_status(report_id, "failed", error=str(exc))
        raise
    await set_status(report_id, "complete", report=report)
    return report
