"""Supervisor: plain code that validates inputs and checks collected context.

It runs twice: at the start of a run, and again after context collection. Routing
between those points lives in graph.routing.
"""

from typing import Any

from core.enums import ApprovalStatus
from core.exceptions import MissingIncidentDataError
from graph.state import IncidentState, Stage


async def supervisor_node(state: IncidentState) -> dict[str, Any]:
    incident = state["incident"]
    if state.get("stage", Stage.START) == Stage.START:
        gaps = []
        if not incident.symptoms and not incident.error_messages:
            gaps.append("incident reports no symptoms or error messages; relying on telemetry")
        return {
            "stage": Stage.START,
            "evidence": [],
            "retry_count": 0,
            "unresolved_critic_issues": False,
            "approval_required": False,
            "approval_status": ApprovalStatus.NOT_REQUIRED,
            "data_gaps": gaps,
        }

    logs = state.get("retrieved_logs")
    metrics = state.get("retrieved_metrics")
    if logs is None and metrics is None and state.get("service_health") is None:
        # Without any telemetry the agents could only guess.
        raise MissingIncidentDataError(
            f"no telemetry could be collected for {incident.service}; analysis stopped",
            details={"incident_id": incident.incident_id, "service": incident.service},
        )

    gaps = []
    if logs is not None and logs.total_lines == 0:
        gaps.append("no log lines in the incident window")
    if metrics is not None and not metrics.series:
        gaps.append("no metrics in the incident window")
    if (
        logs is not None
        and metrics is not None
        and not logs.error_count
        and not metrics.anomalies()
    ):
        gaps.append("telemetry shows no errors or anomalies around the incident time")
    return {"data_gaps": gaps}
