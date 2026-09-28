from typing import Any

import pytest

from agents.critic_agent import code_checks, critic_node, verdict_of
from agents.schemas import CriticReview, CriticVerdict, ToolAction
from auth.permissions import AGENT_PRINCIPAL
from graph.state import AgentDeps, IncidentState
from tests.agent.conftest import ScriptedLLM
from tools.tool_registry import ToolRegistry


def with_changes(state: dict[str, Any], **changes: Any) -> IncidentState:
    updated = dict(state)
    updated.update(changes)
    return updated  # type: ignore[return-value]


def verdicts(state: IncidentState, registry: ToolRegistry) -> set[CriticVerdict]:
    return {v for v, _ in code_checks(state, registry)}


def test_demo_run_passes_all_checks(demo_state: dict[str, Any], registry: ToolRegistry) -> None:
    assert code_checks(demo_state, registry) == []  # type: ignore[arg-type]


def test_invented_evidence_id_is_caught(demo_state: dict[str, Any], registry: ToolRegistry) -> None:
    selected = demo_state["selected_root_cause"]
    fake = selected.model_copy(update={"evidence_for": [*selected.evidence_for, "E999"]})
    state = with_changes(demo_state, selected_root_cause=fake, root_cause_hypotheses=[fake] * 3)
    findings = code_checks(state, registry)
    assert (
        CriticVerdict.REVISE_ROOT_CAUSE,
        f"hypothesis '{fake.title}' cites unknown evidence E999",
    ) in findings


def test_unsupported_root_cause_needs_more_evidence(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    bare = demo_state["selected_root_cause"].model_copy(update={"evidence_for": []})
    state = with_changes(demo_state, selected_root_cause=bare)
    assert CriticVerdict.NEED_MORE_EVIDENCE in verdicts(state, registry)


def test_low_confidence_needs_more_evidence(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    state = with_changes(demo_state, root_cause_confidence=0.1)
    assert verdicts(state, registry) == {CriticVerdict.NEED_MORE_EVIDENCE}


def test_contradicted_root_cause_is_revised(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    selected = demo_state["selected_root_cause"]
    ids = [e.id for e in demo_state["evidence"]]
    contradicted = selected.model_copy(
        update={"evidence_for": ids[:1], "evidence_against": ids[1:3]}
    )
    state = with_changes(demo_state, selected_root_cause=contradicted)
    assert CriticVerdict.REVISE_ROOT_CAUSE in verdicts(state, registry)


def test_rollback_of_unknown_deployment_is_caught(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    plan = demo_state["remediation_plan"]
    step = plan.steps[1].model_copy(
        update={
            "action": ToolAction(
                tool="rollback_deployment", service="checkout-api", deployment_id="dep-99999"
            )
        }
    )
    bad_plan = plan.model_copy(update={"steps": [plan.steps[0], step]})
    findings = code_checks(with_changes(demo_state, remediation_plan=bad_plan), registry)
    assert any("dep-99999, which is not in the evidence" in m for _, m in findings)


def test_plan_without_mitigation_is_revised(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    plan = demo_state["remediation_plan"]
    diagnostic_only = plan.model_copy(update={"steps": plan.steps[:1]})
    state = with_changes(demo_state, remediation_plan=diagnostic_only)
    assert verdicts(state, registry) == {CriticVerdict.REVISE_REMEDIATION}


def test_evidence_problems_take_priority() -> None:
    findings = [
        (CriticVerdict.REVISE_REMEDIATION, "a"),
        (CriticVerdict.NEED_MORE_EVIDENCE, "b"),
        (CriticVerdict.REVISE_ROOT_CAUSE, "c"),
    ]
    assert verdict_of(findings) is CriticVerdict.NEED_MORE_EVIDENCE
    assert verdict_of([]) is CriticVerdict.APPROVE


async def test_model_cannot_approve_over_failed_checks(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    llm = ScriptedLLM(CriticReview=[CriticReview(verdict="approve", confidence=0.9, issues=[])])
    deps = AgentDeps(tools=registry, llm=llm, principal=AGENT_PRINCIPAL)
    update = await critic_node(deps, with_changes(demo_state, root_cause_confidence=0.1))
    assert update["critic_feedback"].verdict is CriticVerdict.NEED_MORE_EVIDENCE
    assert update["retry_count"] == demo_state["retry_count"] + 1


async def test_model_may_be_stricter_than_checks(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    strict = CriticReview(verdict="revise_remediation", confidence=0.4, issues=["too vague"])
    deps = AgentDeps(
        tools=registry, llm=ScriptedLLM(CriticReview=[strict]), principal=AGENT_PRINCIPAL
    )
    update = await critic_node(deps, demo_state)  # type: ignore[arg-type]
    assert update["critic_feedback"] == strict


@pytest.mark.parametrize(("retries", "expect_retry"), [(0, True), (2, True), (3, False)])
async def test_retry_budget(
    demo_state: dict[str, Any], registry: ToolRegistry, retries: int, expect_retry: bool
) -> None:
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL, max_retries=3)
    state = with_changes(demo_state, root_cause_confidence=0.1, retry_count=retries)
    update = await critic_node(deps, state)
    if expect_retry:
        assert update["retry_count"] == retries + 1
        assert "unresolved_critic_issues" not in update
    else:
        assert "retry_count" not in update
        assert update["unresolved_critic_issues"] is True
