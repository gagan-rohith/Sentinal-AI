import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Any, Protocol

import structlog
from langsmith import trace
from pydantic import BaseModel, ValidationError

from auth.permissions import Principal
from auth.rbac import Permission
from core.exceptions import (
    ApprovalRequiredError,
    MalformedToolResponseError,
    SentinelError,
    ToolInputError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from core.models import ServiceHealth
from data.loader import load_runbooks
from observability.metrics import record_tool_call
from retrieval.hybrid_search import HybridSearcher
from tools.backend import SimulatedOpsBackend
from tools.common import ActionResult, WindowQuery
from tools.deployments import (
    DeploymentQuery,
    DeploymentStatusResult,
    RecentDeploymentsResult,
    RollbackRequest,
    get_deployment_status,
    get_recent_deployments,
    rollback_deployment,
)
from tools.kubernetes import (
    PodsQuery,
    PodsResult,
    RestartRequest,
    get_kubernetes_pods,
    restart_service,
)
from tools.logs import LogsQuery, LogsResult, get_recent_logs
from tools.metrics import MetricsResult, get_service_metrics
from tools.runbooks import RunbookDocument, RunbookLibrary, RunbookQuery
from tools.search import (
    KnowledgeQuery,
    SearchQuery,
    SearchResults,
    search_knowledge,
    search_runbooks,
    search_similar_incidents,
)
from tools.service_health import HealthQuery, get_service_health
from tools.tickets import Ticket, TicketRequest, TicketStore

log = structlog.get_logger(__name__)

Handler = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Handler
    permission: Permission
    destructive: bool = False
    timeout_s: float = 5.0


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    latency_ms: float
    started_at: datetime
    destructive: bool
    error: str | None = None


@dataclass(frozen=True)
class ToolResult:
    output: BaseModel
    record: ToolCallRecord


class ApprovalVerifier(Protocol):
    async def verify(self, approval_id: str, tool: str, arguments: Mapping[str, Any]) -> bool: ...


class DenyAllApprovals:
    async def verify(self, approval_id: str, tool: str, arguments: Mapping[str, Any]) -> bool:
        return False


class ToolRegistry:
    def __init__(self, approvals: ApprovalVerifier | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self.approvals: ApprovalVerifier = approvals or DenyAllApprovals()

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool '{spec.name}' is already registered")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise ToolNotFoundError(f"tool '{name}' is not registered") from None

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        principal: Principal,
        *,
        approval_id: str | None = None,
        recorder: list[ToolCallRecord] | None = None,
    ) -> ToolResult:
        # A LangSmith span per tool call; a no-op unless tracing is configured.
        async with trace(
            name, run_type="tool", inputs=dict(arguments), metadata={"principal": principal.subject}
        ) as span:
            result = await self._invoke(
                name, arguments, principal, approval_id=approval_id, recorder=recorder
            )
            span.end(outputs=result.output.model_dump(mode="json"))
            return result

    async def _invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        principal: Principal,
        *,
        approval_id: str | None,
        recorder: list[ToolCallRecord] | None,
    ) -> ToolResult:
        spec = self.get(name)
        started_at = datetime.now(UTC)
        started = time.perf_counter()

        def record(status: ToolCallStatus, error: str | None = None) -> ToolCallRecord:
            entry = ToolCallRecord(
                tool=name,
                arguments=dict(arguments),
                status=status,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                started_at=started_at,
                destructive=spec.destructive,
                error=error,
            )
            if recorder is not None:
                recorder.append(entry)
            record_tool_call(name, status.value, entry.latency_ms)
            log.info(
                "tool_call",
                tool=name,
                status=status.value,
                latency_ms=entry.latency_ms,
                principal=principal.subject,
                error=error,
            )
            return entry

        try:
            principal.require(spec.permission)
            try:
                parsed = spec.input_model.model_validate(dict(arguments))
            except ValidationError as exc:
                raise ToolInputError(
                    f"invalid arguments for tool '{name}'",
                    details={
                        "errors": exc.errors(
                            include_url=False, include_context=False, include_input=False
                        )
                    },
                ) from exc
            if spec.destructive:
                await self._check_approval(spec, approval_id, parsed.model_dump(mode="json"))
            try:
                raw = await asyncio.wait_for(spec.handler(parsed), timeout=spec.timeout_s)
            except TimeoutError:
                raise ToolTimeoutError(
                    f"tool '{name}' timed out after {spec.timeout_s}s",
                    details={"tool": name, "timeout_s": spec.timeout_s},
                ) from None
            output = self._validate_output(spec, raw)
        except (ApprovalRequiredError, SentinelError) as exc:
            status = {
                "forbidden": ToolCallStatus.DENIED,
                "approval_required": ToolCallStatus.DENIED,
                "tool_timeout": ToolCallStatus.TIMEOUT,
            }.get(exc.code, ToolCallStatus.ERROR)
            record(status, exc.message)
            raise
        except Exception as exc:
            record(ToolCallStatus.ERROR, f"{type(exc).__name__}: {exc}")
            raise
        return ToolResult(output=output, record=record(ToolCallStatus.SUCCESS))

    async def _check_approval(
        self, spec: ToolSpec, approval_id: str | None, arguments: Mapping[str, Any]
    ) -> None:
        if approval_id is None or not await self.approvals.verify(
            approval_id, spec.name, arguments
        ):
            raise ApprovalRequiredError(
                f"tool '{spec.name}' changes production state and needs an approved request",
                details={"tool": spec.name, "approval_id": approval_id},
            )

    @staticmethod
    def _validate_output(spec: ToolSpec, raw: Any) -> BaseModel:
        if isinstance(raw, spec.output_model):
            return raw
        try:
            return spec.output_model.model_validate(raw)
        except ValidationError as exc:
            raise MalformedToolResponseError(
                f"tool '{spec.name}' returned a response that does not match "
                f"{spec.output_model.__name__}",
                details={
                    "errors": exc.errors(
                        include_url=False, include_context=False, include_input=False
                    )
                },
            ) from exc


def build_default_registry(
    backend: SimulatedOpsBackend,
    tickets: TicketStore,
    searcher: HybridSearcher,
    approvals: ApprovalVerifier | None = None,
    timeout_s: float = 5.0,
    runbooks: RunbookLibrary | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(approvals)
    read = Permission.READ_TOOLS
    runbooks = runbooks or RunbookLibrary(load_runbooks())
    specs = [
        ToolSpec(
            "get_runbook",
            "Full runbook by id, split into sections.",
            RunbookQuery,
            RunbookDocument,
            runbooks.get,
            read,
        ),
        ToolSpec(
            "search_runbooks",
            "Hybrid (BM25 + vector) search over runbook sections.",
            SearchQuery,
            SearchResults,
            partial(search_runbooks, searcher),
            read,
        ),
        ToolSpec(
            "search_similar_incidents",
            "Hybrid search over resolved incidents, including their root causes.",
            SearchQuery,
            SearchResults,
            partial(search_similar_incidents, searcher),
            read,
        ),
        ToolSpec(
            "search_knowledge",
            "Search runbooks, incidents, service docs and log snippets with filters.",
            KnowledgeQuery,
            SearchResults,
            partial(search_knowledge, searcher),
            read,
        ),
        ToolSpec(
            "get_service_health",
            "Current health status of a service derived from metrics.",
            HealthQuery,
            ServiceHealth,
            partial(get_service_health, backend),
            read,
        ),
        ToolSpec(
            "get_recent_logs",
            "Log lines for a service in a time window, with error summary.",
            LogsQuery,
            LogsResult,
            partial(get_recent_logs, backend),
            read,
        ),
        ToolSpec(
            "get_service_metrics",
            "Metric series for a service with baseline comparison.",
            WindowQuery,
            MetricsResult,
            partial(get_service_metrics, backend),
            read,
        ),
        ToolSpec(
            "get_deployment_status",
            "Currently running and previous deployment of a service.",
            DeploymentQuery,
            DeploymentStatusResult,
            partial(get_deployment_status, backend),
            read,
        ),
        ToolSpec(
            "get_recent_deployments",
            "Most recent deployments of a service, newest first.",
            DeploymentQuery,
            RecentDeploymentsResult,
            partial(get_recent_deployments, backend),
            read,
        ),
        ToolSpec(
            "get_kubernetes_pods",
            "Pods and their status in a Kubernetes namespace.",
            PodsQuery,
            PodsResult,
            partial(get_kubernetes_pods, backend),
            read,
        ),
        ToolSpec(
            "create_incident_ticket",
            "Open a ticket in the ticketing system.",
            TicketRequest,
            Ticket,
            tickets.create,
            Permission.CREATE_TICKETS,
        ),
        ToolSpec(
            "restart_service",
            "Rolling restart of every pod of a service.",
            RestartRequest,
            ActionResult,
            partial(restart_service, backend),
            Permission.EXECUTE_REMEDIATION,
            destructive=True,
        ),
        ToolSpec(
            "rollback_deployment",
            "Roll a service back to the deployment before the given one.",
            RollbackRequest,
            ActionResult,
            partial(rollback_deployment, backend),
            Permission.EXECUTE_REMEDIATION,
            destructive=True,
        ),
    ]
    for spec in specs:
        registry.register(ToolSpec(**{**spec.__dict__, "timeout_s": timeout_s}))
    return registry
