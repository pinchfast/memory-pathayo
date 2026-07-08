import uuid

from fastapi import APIRouter, Depends, status

from kgmemory.core.openapi import ORG_PROTECTED_RESPONSES
from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization
from kgmemory.worker import queue

from .schemas import ReportAccepted, ReportRequest, ReportStatus
from .service import get_status, set_status

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_EXAMPLE = {
    "report_type": "weekly",
    "language": "en",
    "project": "api",
}
REPORT_RESPONSE_EXAMPLE = {"report_id": "f1e2d3c4b5a6", "status": "queued"}


@router.post(
    "/",
    response_model=ReportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a report",
    description=(
        "Enqueue an LLM-composed report (weekly / status / risk / founder_summary) "
        "in the org's preferred language. The report is generated from the org's "
        "facts, project states, and person credibility states. Returns a "
        "`report_id` — poll `GET /reports/{report_id}` for the result."
    ),
    responses={
        **ORG_PROTECTED_RESPONSES,
        202: {
            "description": "Report generation queued",
            "content": {"application/json": {"example": REPORT_RESPONSE_EXAMPLE}},
        },
    },
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def request_report(payload: ReportRequest, org: Organization = Depends(get_current_org)):
    report_id = uuid.uuid4().hex
    await set_status(report_id, "queued")
    await queue.enqueue(
        "generate_report_task",
        report_id=report_id,
        graph_name=org.graph_name,
        payload=payload.model_dump(),
        key=f"report:{report_id}",
        retries=2,
    )
    return ReportAccepted(report_id=report_id)


@router.get(
    "/{report_id}",
    response_model=ReportStatus,
    summary="Check report status",
    description="Poll the status of an async report job. States: `queued` → `running` → `complete` (with report) or `failed` (with error).",
    responses=ORG_PROTECTED_RESPONSES,
    openapi_extra={"security": [{"OrgAPIKey": []}]},
)
async def report_status(report_id: str, org: Organization = Depends(get_current_org)):
    record = await get_status(report_id)
    if record is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown report_id")
    return ReportStatus(**record)
