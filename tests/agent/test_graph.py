from collections import Counter

import pytest

from agents.schemas import CriticReview, SearchPlan
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import MissingIncidentDataError
from core.models import Incident
from graph.state import AgentDeps
from tests.agent.conftest import ScriptedLLM, run_graph
from tools.tool_registry import ToolRegistry

MORE_EVIDENCE = CriticReview(verdict="need_more_evidence", confidence=0.3, issues=["thin evidence"])
REVISE_PLAN = CriticReview(verdict="revise_remediation", confidence=0.4, issues=["plan too vague"])
APPROVE = CriticReview(verdict="approve", confidence=0.9, issues=[])


def agents_run(final: dict[str, object]) -> Counter[str]:
    return Counter(c.agent for c in final["agent_calls"])  # type: ignore[attr-defined]


async def test_critic_retry_loops_back_to_retrieval(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    llm = ScriptedLLM(CriticReview=[MORE_EVIDENCE, APPROVE])
    final = await run_graph(AgentDeps(registry, llm, AGENT_PRINCIPAL), demo_incident)

    assert final["retry_count"] == 1
    assert not final["unresolved_critic_issues"]
    counts = agents_run(final)
    assert counts["retrieval"] == counts["root_cause"] == counts["critic"] == 2
    assert final["final_report"].mode == "mixed"


async def test_retry_cap_prevents_infinite_loop(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    llm = ScriptedLLM(CriticReview=[REVISE_PLAN])  # rejects forever
    deps = AgentDeps(registry, llm, AGENT_PRINCIPAL, max_retries=3)
    final = await run_graph(deps, demo_incident)

    report = final["final_report"]
    assert report.retries == 3
    assert report.unresolved_critic_issues
    assert "Unresolved critic issue: plan too vague" in report.postmortem.open_questions
    counts = agents_run(final)
    assert counts["critic"] == 4
    assert counts["remediation"] == 4
    assert counts["retrieval"] == 1


async def test_llm_outputs_are_used_when_available(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    llm = ScriptedLLM(SearchPlan=[SearchPlan(queries=["hikari pool exhausted postgres"])])
    final = await run_graph(AgentDeps(registry, llm, AGENT_PRINCIPAL), demo_incident)
    assert final["search_queries"] == ["hikari pool exhausted postgres"]
    modes = {c.agent: c.mode for c in final["agent_calls"]}
    assert modes["retrieval"] == "llm"
    assert modes["triage"] == "fallback"


async def test_bad_deployment_is_rolled_back_with_approval(
    registry: ToolRegistry, incidents: list[Incident]
) -> None:
    incident = next(i for i in incidents if i.root_cause_category == "bad_deployment")
    final = await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), incident)

    assert final["selected_root_cause"].category == "bad_deployment"
    actions = [s.action for s in final["remediation_plan"].steps if s.action]
    rollback = next(a for a in actions if a.tool == "rollback_deployment")
    assert rollback.deployment_id == incident.deployment_id
    assert final["approval_required"]


async def test_unknown_service_stops_with_typed_error(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    ghost = demo_incident.model_copy(update={"service": "ghost-service"})
    with pytest.raises(MissingIncidentDataError, match="no telemetry"):
        await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), ghost)


async def test_quiet_window_is_reported_as_data_gap(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    quiet = demo_incident.model_copy(
        update={"timestamp": demo_incident.timestamp.replace(year=2025)}
    )
    final = await run_graph(AgentDeps(registry, None, AGENT_PRINCIPAL), quiet)
    assert "no log lines in the incident window" in final["data_gaps"]
    assert final["final_report"].data_gaps == final["data_gaps"]
