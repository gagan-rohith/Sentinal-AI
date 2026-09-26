from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.container import Container
from app.dependencies import get_container

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, container: Container = Depends(get_container)
) -> HealthResponse:
    checks: dict[str, str] = {}
    try:
        checks["database"] = "ok" if await container.db.ping() else "error"
    except Exception as exc:  # reported in the response, not swallowed
        checks["database"] = f"error: {type(exc).__name__}"
    checks["incidents"] = "ok" if await container.incidents.count() > 0 else "empty"

    healthy = checks["database"] == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version="0.1.0",
        environment=container.settings.app_env,
        checks=checks,
    )
