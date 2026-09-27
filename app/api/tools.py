from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.container import Container
from app.dependencies import get_container, get_principal
from auth.permissions import Principal
from core.enums import Environment, LogLevel, SourceType
from retrieval.models import Fusion, SearchMode
from tools.deployments import RecentDeploymentsResult
from tools.logs import LogsResult
from tools.metrics import MetricsResult
from tools.search import SearchResults

router = APIRouter(prefix="/tools", tags=["tools"])

# Permission checks happen inside the tool registry, the same path agents and MCP use.


def _window(minutes: int, end_time: datetime | None) -> dict[str, Any]:
    return {"minutes": minutes, "end_time": end_time}


@router.get("/logs/{service}", response_model=LogsResult)
async def logs(
    service: str,
    minutes: int = Query(default=30, ge=1, le=1440),
    end_time: datetime | None = None,
    min_level: LogLevel = LogLevel.INFO,
    limit: int = Query(default=200, ge=1, le=2000),
    container: Container = Depends(get_container),
    principal: Principal = Depends(get_principal),
) -> Any:
    args = {
        "service": service,
        **_window(minutes, end_time),
        "min_level": min_level,
        "limit": limit,
    }
    result = await container.tools.invoke("get_recent_logs", args, principal)
    return result.output


@router.get("/metrics/{service}", response_model=MetricsResult)
async def metrics(
    service: str,
    minutes: int = Query(default=30, ge=1, le=1440),
    end_time: datetime | None = None,
    container: Container = Depends(get_container),
    principal: Principal = Depends(get_principal),
) -> Any:
    args = {"service": service, **_window(minutes, end_time)}
    result = await container.tools.invoke("get_service_metrics", args, principal)
    return result.output


@router.get("/deployments/{service}", response_model=RecentDeploymentsResult)
async def deployments(
    service: str,
    end_time: datetime | None = None,
    limit: int = Query(default=5, ge=1, le=50),
    container: Container = Depends(get_container),
    principal: Principal = Depends(get_principal),
) -> Any:
    args = {"service": service, "end_time": end_time, "limit": limit}
    result = await container.tools.invoke("get_recent_deployments", args, principal)
    return result.output


@router.get("/search", response_model=SearchResults)
async def search(
    q: str = Query(min_length=3, max_length=1000, description="Search query"),
    service: str | None = None,
    environment: Environment | None = None,
    source_type: list[SourceType] | None = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=20),
    mode: SearchMode = SearchMode.HYBRID,
    fusion: Fusion = Fusion.RRF,
    container: Container = Depends(get_container),
    principal: Principal = Depends(get_principal),
) -> Any:
    args = {
        "query": q,
        "service": service,
        "environment": environment,
        "source_types": source_type,
        "top_k": top_k,
        "mode": mode,
        "fusion": fusion,
    }
    result = await container.tools.invoke("search_knowledge", args, principal)
    return result.output
