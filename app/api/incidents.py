from fastapi import APIRouter, Depends, Path, Query, status

from app.container import Container
from app.dependencies import get_container, require
from auth.permissions import Principal
from auth.rbac import Permission
from core.enums import IncidentStatus, Severity
from core.models import Incident, IncidentCreate

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[Incident])
async def list_incidents(
    service: str | None = None,
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    severity: Severity | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_INCIDENTS)),
) -> list[Incident]:
    return await container.incidents.list_incidents(
        service=service, status=status_filter, severity=severity, limit=limit, offset=offset
    )


@router.get("/{incident_id}", response_model=Incident)
async def get_incident(
    incident_id: str = Path(pattern=r"^INC-[0-9]{4,}$"),
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_INCIDENTS)),
) -> Incident:
    return await container.incidents.get(incident_id)


@router.post("", response_model=Incident, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.WRITE_INCIDENTS)),
) -> Incident:
    return await container.incidents.create(payload)
