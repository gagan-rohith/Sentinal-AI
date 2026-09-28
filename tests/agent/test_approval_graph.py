from typing import Any

import pytest

from auth.permissions import AGENT_PRINCIPAL
from core.enums import ApprovalStatus, Role
from core.models import Incident
from graph.routing import route_after_approval, route_after_critic
from graph.state import AgentDeps, IncidentState
from tests.agent.conftest import decision, run_graph
from tools.tool_registry import ToolCallStatus, ToolRegistry


async def test_destructive_plan_pauses_before_postmortem(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    paused = await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), demo_incident, None)
    assert paused["__next__"] == ("human_approval",)
    assert "final_report" not in paused
    assert "tool_execution_result" not in paused


async def test_approval_executes_through_the_registry(
    permissive_registry: ToolRegistry, demo_incident: Incident
) -> None:
    deps = AgentDeps(permissive_registry, None, AGENT_PRINCIPAL)
    final = await run_graph(deps, demo_incident, decision(approved=True))

    [executed] = final["tool_execution_result"]
    assert (executed.tool, executed.status) == ("restart_service", "succeeded")
    assert executed.arguments == {"service": "checkout-api"}
    restart_call = next(c for c in final["tool_calls"] if c.tool == "restart_service")
    assert restart_call.destructive
    assert restart_call.status is ToolCallStatus.SUCCESS

    report = final["final_report"]
    assert report.approval_status is ApprovalStatus.APPROVED
    assert report.approval.decided_by == "tester-admin"
    assert "Approved by tester-admin" in report.postmortem.remediation
    assert any("restart_service succeeded" in e.description for e in report.timeline)


async def test_rejection_executes_nothing(demo_state: dict[str, Any]) -> None:
    report = demo_state["final_report"]
    assert report.approval_status is ApprovalStatus.REJECTED
    assert report.executed_actions == []
    assert not any(c.tool == "restart_service" for c in demo_state["tool_calls"])
    assert "not during peak traffic" in report.postmortem.remediation


async def test_graph_approval_alone_cannot_bypass_the_registry(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    # The default registry has no approval store behind it, so even an "approved"
    # decision in graph state is refused at the tool layer.
    final = await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), demo_incident,
                            decision(approved=True))  # fmt: skip
    [executed] = final["tool_execution_result"]
    assert executed.status == "failed"
    assert executed.message.startswith("approval_required")


async def test_non_admin_approver_is_refused_at_execution(
    permissive_registry: ToolRegistry, demo_incident: Incident
) -> None:
    deps = AgentDeps(permissive_registry, None, AGENT_PRINCIPAL)
    final = await run_graph(deps, demo_incident, decision(approved=True, role=Role.OPERATOR))
    [executed] = final["tool_execution_result"]
    assert executed.status == "failed"
    assert executed.message.startswith("forbidden")


async def test_safe_plan_skips_the_gate(registry: ToolRegistry, incidents: list[Incident]) -> None:
    incident = next(i for i in incidents if i.root_cause_category == "k8s_oom_killed")
    final = await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), incident, None)
    assert final["__next__"] == ()
    assert final["final_report"].approval_status is ApprovalStatus.NOT_REQUIRED
    assert final["final_report"].approval is None


def test_routing_through_the_gate() -> None:
    approved: IncidentState = {"approval_status": ApprovalStatus.APPROVED}
    rejected: IncidentState = {"approval_status": ApprovalStatus.REJECTED}
    assert route_after_approval(approved) == "action_execution"
    assert route_after_approval(rejected) == "postmortem"


@pytest.mark.parametrize(("required", "target"), [(True, "human_approval"), (False, "postmortem")])
def test_critic_approval_leads_to_gate_only_when_required(
    demo_state: dict[str, Any], required: bool, target: str
) -> None:
    state: IncidentState = {
        "critic_feedback": demo_state["critic_feedback"],
        "approval_required": required,
    }
    assert route_after_critic(state) == target
