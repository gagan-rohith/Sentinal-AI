from fastapi import APIRouter, Body, Depends, Path, status
from pydantic import BaseModel, Field

from agents.schemas import FinalReport
from app.container import Container
from app.dependencies import get_container, require
from auth.permissions import Principal
from auth.rbac import Permission
from storage.approvals import ApprovalRecord
from storage.runs import RunRecord

router = APIRouter(prefix="/agents", tags=["agents"])

RUN_ID = Path(pattern=r"^run-[0-9a-f]{12}$")


class ApproveBody(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RejectBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.post(
    "/analyze/{incident_id}",
    response_model=RunRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a multi-agent analysis of an incident",
)
async def analyze(
    incident_id: str = Path(pattern=r"^INC-[0-9]{4,}$"),
    container: Container = Depends(get_container),
    principal: Principal = Depends(require(Permission.RUN_ANALYSIS)),
) -> RunRecord:
    incident = await container.incidents.get(incident_id)
    return await container.analyzer.start(incident, principal.subject)


@router.get("/status/{run_id}", response_model=RunRecord)
async def run_status(
    run_id: str = RUN_ID,
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> RunRecord:
    return await container.analyzer.runs.get(run_id)


@router.get(
    "/{run_id}/approval",
    response_model=ApprovalRecord,
    summary="The approval request for a paused run and its decision",
)
async def run_approval(
    run_id: str = RUN_ID,
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> ApprovalRecord:
    return await container.analyzer.approvals.for_run(run_id)


@router.post(
    "/{run_id}/approve",
    response_model=RunRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Approve the proposed production changes and resume the run (admin only)",
)
async def approve(
    run_id: str = RUN_ID,
    body: ApproveBody = Body(default_factory=ApproveBody),
    container: Container = Depends(get_container),
    principal: Principal = Depends(require(Permission.EXECUTE_REMEDIATION)),
) -> RunRecord:
    return await container.analyzer.approve(run_id, principal, body.comment)


@router.post(
    "/{run_id}/reject",
    response_model=RunRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reject the proposed changes; the run finishes without executing anything",
)
async def reject(
    body: RejectBody,
    run_id: str = RUN_ID,
    container: Container = Depends(get_container),
    principal: Principal = Depends(require(Permission.REJECT_REMEDIATION)),
) -> RunRecord:
    return await container.analyzer.reject(run_id, principal, body.reason)


@router.get("/{run_id}/report", response_model=FinalReport)
async def run_report(
    run_id: str = RUN_ID,
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> FinalReport:
    return await container.analyzer.runs.report(run_id)
