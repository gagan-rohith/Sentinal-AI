from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.container import Container
from app.dependencies import get_container
from core.exceptions import SearchUnavailableError

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
    checks["search"] = await _search_check(container)

    # Only the database is fatal. Without search the API still serves incidents and tools,
    # so the pod stays in rotation and reports degraded.
    if checks["database"] != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    healthy = all(value == "ok" for value in checks.values())
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version="0.1.0",
        environment=container.settings.app_env,
        checks=checks,
    )


async def _search_check(container: Container) -> str:
    backend = container.search_backend
    if not await backend.ping():
        return f"unavailable ({backend.name})"
    try:
        count = await backend.count()
    except SearchUnavailableError as exc:
        return f"error: {exc.message}"
    return "ok" if count > 0 else "empty index"
