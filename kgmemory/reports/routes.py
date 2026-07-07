import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from kgmemory.orgs.auth import get_current_org
from kgmemory.orgs.models import Organization
from kgmemory.worker import queue

from .schemas import ReportAccepted, ReportRequest, ReportStatus
from .service import get_status, set_status

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/", response_model=ReportAccepted, status_code=status.HTTP_202_ACCEPTED)
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


@router.get("/{report_id}", response_model=ReportStatus)
async def report_status(report_id: str, org: Organization = Depends(get_current_org)):
    record = await get_status(report_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown report_id")
    return ReportStatus(**record)
