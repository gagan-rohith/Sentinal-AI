import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import BaseModel

from auth.permissions import Principal
from auth.rbac import Permission
from core.enums import HealthStatus, LogLevel, Role
from core.exceptions import (
    ApprovalRequiredError,
    InvalidStateError,
    MalformedToolResponseError,
    NotFoundError,
    ToolInputError,
    ToolNotFoundError,
    ToolTimeoutError,
    UnauthorizedActionError,
)
from core.models import Incident
from retrieval.hybrid_search import HybridSearcher
from tools.backend import SimulatedOpsBackend
from tools.common import WindowQuery
from tools.deployments import (
    DeploymentQuery,
    RollbackRequest,
    get_deployment_status,
    rollback_deployment,
)
from tools.kubernetes import PodsQuery, get_kubernetes_pods
from tools.logs import LogsQuery, get_recent_logs, normalize
from tools.metrics import get_service_metrics
from tools.service_health import HealthQuery, get_service_health
from tools.tickets import TicketStore
from tools.tool_registry import (
    ToolCallRecord,
    ToolCallStatus,
    ToolRegistry,
    ToolSpec,
    build_default_registry,
)

OPERATOR = Principal(subject="op", role=Role.OPERATOR, auth_method="test")
ADMIN = Principal(subject="admin", role=Role.ADMIN, auth_method="test")
VIEWER = Principal(subject="viewer", role=Role.VIEWER, auth_method="test")


class ApproveOnly:
    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id

    async def verify(self, approval_id: str, tool: str, arguments: Mapping[str, Any]) -> bool:
        return approval_id == self.approval_id


@pytest.fixture
def registry(backend: SimulatedOpsBackend, searcher: HybridSearcher) -> ToolRegistry:
    return build_default_registry(backend, TicketStore(), searcher, approvals=ApproveOnly("apr-1"))


def test_normalize_groups_volatile_tokens() -> None:
    assert normalize("pod abc123ef failed after 3000ms") == normalize(
        "pod 99ffeedd failed after 12ms"
    )


async def test_logs_at_incident_time_show_pool_errors(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    result = await get_recent_logs(
        backend,
        LogsQuery(service=demo_incident.service, end_time=demo_incident.timestamp, minutes=30),
    )
    assert result.error_count > 0
    assert any("Connection is not available" in e.example for e in result.top_errors)
    assert all(result.start <= e.timestamp <= result.end for e in result.entries)


async def test_logs_respect_min_level_and_limit(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    result = await get_recent_logs(
        backend,
        LogsQuery(
            service=demo_incident.service,
            end_time=demo_incident.timestamp,
            min_level=LogLevel.ERROR,
            limit=3,
        ),
    )
    assert len(result.entries) == 3
    assert all(e.level in {LogLevel.ERROR, LogLevel.FATAL} for e in result.entries)


async def test_metrics_flag_anomalies(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    result = await get_service_metrics(
        backend, WindowQuery(service=demo_incident.service, end_time=demo_incident.timestamp)
    )
    anomalous = {s.name for s in result.anomalies()}
    assert {"db_connections_in_use", "error_rate_pct", "p99_latency_ms"} <= anomalous
    assert "cpu_pct" not in anomalous


async def test_health_is_degraded_during_incident(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    health = await get_service_health(
        backend, HealthQuery(service=demo_incident.service, end_time=demo_incident.timestamp)
    )
    assert health.status is HealthStatus.DEGRADED
    assert health.reasons


async def test_health_reports_missing_telemetry(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    quiet = demo_incident.timestamp.replace(year=2025)
    health = await get_service_health(backend, HealthQuery(service="checkout-api", end_time=quiet))
    assert health.status is HealthStatus.HEALTHY
    assert health.reasons == ["no telemetry in window"]


async def test_deployment_status_shows_distractor_deploy(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    status = await get_deployment_status(
        backend, DeploymentQuery(service="checkout-api", end_time=demo_incident.timestamp)
    )
    assert status.current is not None
    assert status.current.deployment_id == demo_incident.deployment_id
    assert status.minutes_since_deploy == pytest.approx(180, abs=1)
    assert status.previous is not None


async def test_rollback_targets_previous_deployment(
    backend: SimulatedOpsBackend, demo_incident: Incident
) -> None:
    assert demo_incident.deployment_id
    result = await rollback_deployment(
        backend, RollbackRequest(service="checkout-api", deployment_id=demo_incident.deployment_id)
    )
    assert result.details["from_deployment"] == demo_incident.deployment_id
    assert result.details["to_deployment"] != demo_incident.deployment_id
    assert result.simulated


async def test_rollback_of_first_deployment_is_rejected(backend: SimulatedOpsBackend) -> None:
    first = backend.deployments("checkout-api")[0]
    with pytest.raises(InvalidStateError):
        await rollback_deployment(
            backend, RollbackRequest(service="checkout-api", deployment_id=first.deployment_id)
        )


async def test_unknown_service_raises_not_found(backend: SimulatedOpsBackend) -> None:
    with pytest.raises(NotFoundError):
        await get_recent_logs(backend, LogsQuery(service="does-not-exist"))


async def test_pods_listed_per_namespace(backend: SimulatedOpsBackend) -> None:
    result = await get_kubernetes_pods(backend, PodsQuery(namespace="commerce"))
    services = {p.service for p in result.pods}
    assert "checkout-api" in services
    assert all(p.namespace == "commerce" for p in result.pods)


async def test_registry_invokes_and_records(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    calls: list[ToolCallRecord] = []
    result = await registry.invoke(
        "get_recent_logs",
        {"service": "checkout-api", "end_time": demo_incident.timestamp},
        OPERATOR,
        recorder=calls,
    )
    assert result.record.status is ToolCallStatus.SUCCESS
    assert calls == [result.record]


async def test_registry_enforces_permissions(registry: ToolRegistry) -> None:
    calls: list[ToolCallRecord] = []
    with pytest.raises(UnauthorizedActionError):
        await registry.invoke(
            "get_recent_logs", {"service": "checkout-api"}, VIEWER, recorder=calls
        )
    assert calls[0].status is ToolCallStatus.DENIED


async def test_registry_validates_input(registry: ToolRegistry) -> None:
    with pytest.raises(ToolInputError) as exc_info:
        await registry.invoke(
            "get_recent_logs", {"service": "checkout-api", "minutes": 0}, OPERATOR
        )
    assert exc_info.value.details["errors"]


async def test_unknown_tool(registry: ToolRegistry) -> None:
    with pytest.raises(ToolNotFoundError):
        await registry.invoke("drop_database", {}, ADMIN)


async def test_destructive_tool_requires_admin(registry: ToolRegistry) -> None:
    with pytest.raises(UnauthorizedActionError):
        await registry.invoke(
            "restart_service", {"service": "checkout-api"}, OPERATOR, approval_id="apr-1"
        )


@pytest.mark.parametrize("approval_id", [None, "apr-unknown"])
async def test_destructive_tool_requires_valid_approval(
    registry: ToolRegistry, approval_id: str | None
) -> None:
    calls: list[ToolCallRecord] = []
    with pytest.raises(ApprovalRequiredError):
        await registry.invoke(
            "restart_service",
            {"service": "checkout-api"},
            ADMIN,
            approval_id=approval_id,
            recorder=calls,
        )
    assert calls[0].status is ToolCallStatus.DENIED


async def test_destructive_tool_runs_with_approval(registry: ToolRegistry) -> None:
    result = await registry.invoke(
        "restart_service", {"service": "checkout-api"}, ADMIN, approval_id="apr-1"
    )
    assert result.record.destructive
    assert result.output.model_dump()["action"] == "restart_service"


class Echo(BaseModel):
    value: int


def _spec(name: str, handler: Any, timeout_s: float = 5.0) -> ToolSpec:
    return ToolSpec(
        name, "test tool", Echo, Echo, handler, Permission.READ_TOOLS, timeout_s=timeout_s
    )


async def test_registry_times_out_slow_tools() -> None:
    async def slow(_: Echo) -> Echo:
        await asyncio.sleep(1)
        return Echo(value=1)

    registry = ToolRegistry()
    registry.register(_spec("slow", slow, timeout_s=0.01))
    calls: list[ToolCallRecord] = []
    with pytest.raises(ToolTimeoutError):
        await registry.invoke("slow", {"value": 1}, OPERATOR, recorder=calls)
    assert calls[0].status is ToolCallStatus.TIMEOUT


async def test_registry_rejects_malformed_output() -> None:
    async def broken(_: Echo) -> dict[str, str]:
        return {"value": "not a number"}

    registry = ToolRegistry()
    registry.register(_spec("broken", broken))
    with pytest.raises(MalformedToolResponseError):
        await registry.invoke("broken", {"value": 1}, OPERATOR)


async def test_registry_coerces_dict_output() -> None:
    async def plain(inp: Echo) -> dict[str, int]:
        return {"value": inp.value * 2}

    registry = ToolRegistry()
    registry.register(_spec("plain", plain))
    result = await registry.invoke("plain", {"value": 2}, OPERATOR)
    assert result.output == Echo(value=4)


async def test_registry_records_unexpected_errors() -> None:
    async def crash(_: Echo) -> Echo:
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_spec("crash", crash))
    calls: list[ToolCallRecord] = []
    with pytest.raises(RuntimeError):
        await registry.invoke("crash", {"value": 1}, OPERATOR, recorder=calls)
    assert calls[0].status is ToolCallStatus.ERROR
    assert calls[0].error == "RuntimeError: boom"


def test_duplicate_registration_rejected() -> None:
    registry = ToolRegistry()

    async def handler(inp: Echo) -> Echo:
        return inp

    registry.register(_spec("x", handler))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_spec("x", handler))


async def test_search_tools_scope_source_types(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    runbooks = await registry.invoke(
        "search_runbooks", {"query": "database connection pool exhausted"}, OPERATOR
    )
    assert {h["source_type"] for h in runbooks.output.model_dump()["hits"]} == {"runbook"}

    incidents = await registry.invoke(
        "search_similar_incidents",
        {"query": demo_incident.search_text(), "exclude_incident_ids": [demo_incident.incident_id]},
        OPERATOR,
    )
    hits = incidents.output.model_dump()["hits"]
    assert {h["source_type"] for h in hits} == {"incident"}
    assert demo_incident.incident_id not in {h["incident_id"] for h in hits}


def test_default_registry_marks_only_mutating_tools_destructive(registry: ToolRegistry) -> None:
    destructive = {s.name for s in registry.specs() if s.destructive}
    assert destructive == {"restart_service", "rollback_deployment"}
