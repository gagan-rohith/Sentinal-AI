from typing import Any

from agents.evidence import EvidenceKind, add_evidence, render
from agents.postmortem_agent import build_timeline
from agents.remediation_agent import requires_approval, runbooks_for
from agents.schemas import RemediationPlan, Risk, Subsystem
from agents.triage_agent import heuristic_triage
from core.enums import ApprovalStatus, Severity
from core.models import Incident
from tools.tool_registry import ToolRegistry


def test_add_evidence_assigns_ids_and_dedupes_by_source() -> None:
    catalog, first = add_evidence([], EvidenceKind.LOG, "a", "logs:x")
    catalog, again = add_evidence(catalog, EvidenceKind.LOG, "different text", "logs:x")
    catalog, second = add_evidence(catalog, EvidenceKind.METRIC, "b", "metric:y")
    assert (first.id, again.id, second.id) == ("E1", "E1", "E2")
    assert len(catalog) == 2
    assert render(catalog).splitlines()[0] == "[E1] (log) a"
    assert render([]) == "(no evidence collected)"


def test_triage_identifies_database_subsystem(demo_incident: Incident) -> None:
    triage = heuristic_triage(demo_incident)
    assert triage.subsystem is Subsystem.DATABASE
    assert triage.assessed_severity is demo_incident.severity


def test_triage_escalates_when_most_requests_fail(demo_incident: Incident) -> None:
    severe = demo_incident.model_copy(
        update={"severity": Severity.SEV3, "metrics_summary": {"error_rate_pct": 80.0}}
    )
    triage = heuristic_triage(severe)
    assert triage.assessed_severity is Severity.SEV1
    assert "80.0%" in triage.severity_reason


def test_root_cause_rules_out_distractor_deploy(demo_state: dict[str, Any]) -> None:
    selected = demo_state["selected_root_cause"]
    assert selected.category == "postgres_pool_exhaustion"
    deploy = next(h for h in demo_state["root_cause_hypotheses"] if h.category == "bad_deployment")
    deploy_evidence = next(e for e in demo_state["evidence"] if e.kind is EvidenceKind.DEPLOYMENT)
    assert deploy.evidence_against == [deploy_evidence.id]
    assert "Ruled out" in deploy.description
    assert 3 <= len(demo_state["root_cause_hypotheses"]) <= 5


def test_root_cause_cites_traffic_change(demo_state: dict[str, Any]) -> None:
    traffic = next(e for e in demo_state["evidence"] if e.kind is EvidenceKind.CHANGE)
    assert traffic.id in demo_state["selected_root_cause"].evidence_for


def test_demo_plan_restarts_only_with_approval(
    demo_state: dict[str, Any], registry: ToolRegistry
) -> None:
    plan: RemediationPlan = demo_state["remediation_plan"]
    actions = [s.action for s in plan.steps if s.action]
    assert [a.tool for a in actions] == ["restart_service"]
    assert plan.approval_required
    assert demo_state["approval_required"]
    assert plan.overall_risk is Risk.MEDIUM
    # Approval comes from the registry, not from whatever the model claimed.
    unsafe_claim = plan.model_copy(update={"approval_required": False})
    assert requires_approval(unsafe_claim, registry)


def test_runbooks_follow_selected_hypothesis(demo_state: dict[str, Any]) -> None:
    runbooks = runbooks_for(demo_state["selected_root_cause"], demo_state["evidence"])
    assert runbooks[0] == "postgres-connection-pool-exhaustion"


def test_timeline_uses_recorded_timestamps(demo_state: dict[str, Any]) -> None:
    timeline = build_timeline(demo_state)  # type: ignore[arg-type]
    assert [e.timestamp for e in timeline] == sorted(e.timestamp for e in timeline)
    assert timeline[-1].description.startswith("Alert fired")
    assert any(e.description.startswith("First error observed") for e in timeline)
    known = {e.id for e in demo_state["evidence"]} | {demo_state["incident"].incident_id}
    assert {e.source for e in timeline} <= known


def test_final_report_for_demo(demo_state: dict[str, Any]) -> None:
    report = demo_state["final_report"]
    assert report.mode == "heuristic"
    assert report.approval_status is ApprovalStatus.PENDING
    assert report.retries == 0
    assert not report.unresolved_critic_issues
    assert set(report.evidence_ids_cited) <= {e.id for e in report.evidence}
    assert [c.agent for c in report.agent_calls] == [
        "triage", "retrieval", "root_cause", "remediation", "critic", "postmortem",
    ]  # fmt: skip
    assert report.tool_call_count >= 8
