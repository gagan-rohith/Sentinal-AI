from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field

from core.exceptions import InvalidStateError
from core.models import Deployment, ServiceName
from tools.backend import SimulatedOpsBackend
from tools.common import ActionResult


class DeploymentQuery(BaseModel):
    service: ServiceName
    end_time: AwareDatetime | None = None
    limit: int = Field(default=5, ge=1, le=50)


class RecentDeploymentsResult(BaseModel):
    service: str
    as_of: datetime
    deployments: list[Deployment] = Field(description="Newest first")


class DeploymentStatusResult(BaseModel):
    service: str
    as_of: datetime
    current: Deployment | None
    previous: Deployment | None
    minutes_since_deploy: float | None


class RollbackRequest(BaseModel):
    service: ServiceName
    deployment_id: str = Field(pattern=r"^dep-[0-9]+$", description="Deployment to roll back")


async def get_recent_deployments(
    backend: SimulatedOpsBackend, query: DeploymentQuery
) -> RecentDeploymentsResult:
    as_of = query.end_time or backend.now(query.service)
    history = backend.deployments(query.service, until=as_of)
    return RecentDeploymentsResult(
        service=query.service,
        as_of=as_of,
        deployments=list(reversed(history[-query.limit :])),
    )


async def get_deployment_status(
    backend: SimulatedOpsBackend, query: DeploymentQuery
) -> DeploymentStatusResult:
    as_of = query.end_time or backend.now(query.service)
    history = backend.deployments(query.service, until=as_of)
    current = history[-1] if history else None
    return DeploymentStatusResult(
        service=query.service,
        as_of=as_of,
        current=current,
        previous=history[-2] if len(history) > 1 else None,
        minutes_since_deploy=(
            round((as_of - current.timestamp).total_seconds() / 60, 1) if current else None
        ),
    )


async def rollback_deployment(
    backend: SimulatedOpsBackend, request: RollbackRequest
) -> ActionResult:
    target = backend.find_deployment(request.service, request.deployment_id)
    history = backend.deployments(request.service, until=target.timestamp)
    if len(history) < 2:
        raise InvalidStateError(
            f"no earlier deployment to roll back to from {request.deployment_id}",
            details={"deployment_id": request.deployment_id},
        )
    previous = history[-2]
    return ActionResult(
        action="rollback_deployment",
        service=request.service,
        status="completed",
        message=(
            f"Rolled back {request.service} from {target.version} to {previous.version} "
            "(simulated)."
        ),
        executed_at=backend.now(request.service),
        details={
            "from_deployment": target.deployment_id,
            "to_deployment": previous.deployment_id,
            "to_version": previous.version,
        },
    )
