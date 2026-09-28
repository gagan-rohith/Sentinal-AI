from fastapi import APIRouter, Depends, Path, status

from agents.schemas import FinalReport
from app.container import Container
from app.dependencies import get_container, require
from auth.permissions import Principal
from auth.rbac import Permission
from storage.runs import RunRecord

router = APIRouter(prefix="/agents", tags=["agents"])

RUN_ID = Path(pattern=r"^run-[0-9a-f]{12}$")


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


@router.get("/{run_id}/report", response_model=FinalReport)
async def run_report(
    run_id: str = RUN_ID,
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> FinalReport:
    return await container.analyzer.runs.report(run_id)
