"""Human approval gate and execution of approved actions. Both are plain code."""

from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from agents.schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ExecutedAction,
    ProposedAction,
)
from auth.permissions import Principal
from core.enums import ApprovalStatus
from core.exceptions import SentinelError
from graph.state import AgentDeps, IncidentState
from tools.common import ActionResult
from tools.tool_registry import ToolCallRecord


def build_request(deps: AgentDeps, state: IncidentState) -> ApprovalRequest:
    plan = state["remediation_plan"]
    selected = state["selected_root_cause"]
    review = state.get("critic_feedback")
    actions = [
        ProposedAction(
            tool=step.action.tool,
            arguments=step.action.arguments(),
            description=step.description,
            risk=step.risk,
        )
        for step in plan.steps
        if step.action and deps.tools.get(step.action.tool).destructive
    ]
    return ApprovalRequest(
        run_id=state["run_id"],
        incident_id=state["incident"].incident_id,
        service=state["incident"].service,
        root_cause=selected.title,
        root_cause_confidence=state.get("root_cause_confidence", selected.confidence),
        actions=actions,
        overall_risk=plan.overall_risk,
        rollback_plan=plan.rollback_plan,
        unresolved_critic_issues=(
            review.issues if review and state.get("unresolved_critic_issues") else []
        ),
    )


async def human_approval_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    request = build_request(deps, state)
    # The graph pauses here and the checkpoint is saved. The node runs again from the
    # top on resume, and interrupt() then returns the human's decision.
    decision = ApprovalDecision.model_validate(interrupt(request.model_dump(mode="json")))
    return {
        "approval_request": request,
        "approval_decision": decision,
        "approval_status": ApprovalStatus.APPROVED
        if decision.approved
        else ApprovalStatus.REJECTED,
    }


async def action_execution_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    request = state["approval_request"]
    decision = state["approval_decision"]
    # Actions run as the human who approved them, never as the agent identity.
    approver = Principal(subject=decision.decided_by, role=decision.role, auth_method="approval")
    calls: list[ToolCallRecord] = []
    executed: list[ExecutedAction] = []

    for action in request.actions:
        try:
            result = await deps.tools.invoke(
                action.tool,
                action.arguments,
                approver,
                approval_id=decision.approval_id,
                recorder=calls,
            )
        except SentinelError as exc:
            executed.append(
                ExecutedAction(
                    tool=action.tool,
                    arguments=action.arguments,
                    status="failed",
                    message=f"{exc.code}: {exc.message}",
                    executed_at=datetime.now(UTC),
                )
            )
            # Stop at the first failure rather than applying later steps on a bad base.
            break
        message = result.output.message if isinstance(result.output, ActionResult) else ""
        executed.append(
            ExecutedAction(
                tool=action.tool,
                arguments=action.arguments,
                status="succeeded",
                message=message,
                executed_at=datetime.now(UTC),
            )
        )
    return {"tool_execution_result": executed, "tool_calls": calls}
