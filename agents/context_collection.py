"""Context collection: a plain function, not an agent. It gathers telemetry in parallel."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from agents.common import try_tool
from agents.evidence import Evidence, EvidenceKind, add_evidence
from core.models import Incident, ServiceHealth
from graph.state import AgentDeps, DeploymentContext, IncidentState, Stage
from tools.deployments import DeploymentStatusResult, RecentDeploymentsResult
from tools.logs import LogsResult, normalize
from tools.metrics import MetricsResult
from tools.tool_registry import ToolCallRecord

WINDOW_MINUTES = 30
DEPLOY_LOOKBACK = timedelta(hours=24)


def _minutes_before(incident: Incident, at: datetime) -> int:
    return round((incident.timestamp - at).total_seconds() / 60)


def telemetry_evidence(
    incident: Incident,
    health: ServiceHealth | None,
    logs: LogsResult | None,
    metrics: MetricsResult | None,
    recent: RecentDeploymentsResult | None,
) -> list[Evidence]:
    catalog: list[Evidence] = []
    service = incident.service

    if health is not None:
        reasons = "; ".join(health.reasons) or "no issues detected"
        catalog, _ = add_evidence(
            catalog, EvidenceKind.HEALTH, f"{service} health is {health.status}: {reasons}",
            f"health:{service}", health.observed_at,
        )  # fmt: skip

    if logs is not None:
        for pattern in logs.top_errors:
            first = min(
                (e.timestamp for e in logs.entries if normalize(e.message) == pattern.pattern),
                default=None,
            )
            catalog, _ = add_evidence(
                catalog,
                EvidenceKind.LOG,
                f"{pattern.count}x {pattern.level} in {service} logs: {pattern.example}",
                f"logs:{service}:{pattern.pattern}",
                first,
                count=pattern.count,
            )

    if metrics is not None:
        for summary in metrics.anomalies():
            pct = f" ({summary.change_pct:+}%)" if summary.change_pct is not None else ""
            catalog, _ = add_evidence(
                catalog,
                EvidenceKind.METRIC,
                f"{summary.name} went from {summary.baseline} to {summary.latest} "
                f"{summary.unit}{pct}, peak {summary.peak}",
                f"metric:{service}:{summary.name}",
                metrics.end,
                metric=summary.name,
            )

    if recent is not None:
        for dep in recent.deployments:
            if incident.timestamp - dep.timestamp > DEPLOY_LOOKBACK:
                continue
            catalog, _ = add_evidence(
                catalog,
                EvidenceKind.DEPLOYMENT,
                f"Deployment {dep.deployment_id} ({dep.version}) of {service}, "
                f"{_minutes_before(incident, dep.timestamp)} min before the alert: "
                f"{dep.change_summary}",
                f"deployment:{dep.deployment_id}",
                dep.timestamp,
                deployment_id=dep.deployment_id,
            )

    for change in incident.recent_changes:
        catalog, _ = add_evidence(
            catalog,
            EvidenceKind.CHANGE,
            f"{change.change_type} change {change.change_id}, "
            f"{_minutes_before(incident, change.timestamp)} min before the alert: "
            f"{change.description}",
            f"deployment:{change.change_id}"
            if change.change_id.startswith("dep-")
            else f"change:{change.change_id}",
            change.timestamp,
        )
    return catalog


async def context_collection_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    incident = state["incident"]
    calls: list[ToolCallRecord] = []
    gaps: list[str] = []
    window = {"service": incident.service, "end_time": incident.timestamp}

    health, logs, metrics, status, recent = await asyncio.gather(
        try_tool(deps, "get_service_health", window, ServiceHealth, calls, gaps),
        try_tool(
            deps, "get_recent_logs", {**window, "minutes": WINDOW_MINUTES}, LogsResult,
            calls, gaps,
        ),
        try_tool(
            deps, "get_service_metrics", {**window, "minutes": WINDOW_MINUTES}, MetricsResult,
            calls, gaps,
        ),
        try_tool(deps, "get_deployment_status", window, DeploymentStatusResult, calls, gaps),
        try_tool(deps, "get_recent_deployments", window, RecentDeploymentsResult, calls, gaps),
    )  # fmt: skip

    update: dict[str, Any] = {
        "stage": Stage.CONTEXT_COLLECTED,
        "evidence": telemetry_evidence(incident, health, logs, metrics, recent),
        "tool_calls": calls,
        "data_gaps": gaps,
    }
    if health is not None:
        update["service_health"] = health
    if logs is not None:
        update["retrieved_logs"] = logs
    if metrics is not None:
        update["retrieved_metrics"] = metrics
    if status is not None and recent is not None:
        update["deployment_context"] = DeploymentContext(status=status, recent=recent)
    return update
