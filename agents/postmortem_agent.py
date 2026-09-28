from typing import Any, Literal

from agents import prompts
from agents.evidence import EvidenceKind, render
from agents.llm import run_step
from agents.schemas import (
    AgentCall,
    FinalReport,
    PostmortemDraft,
    StepKind,
    TimelineEvent,
)
from core.enums import ApprovalStatus
from graph.state import AgentDeps, IncidentState


def build_timeline(state: IncidentState) -> list[TimelineEvent]:
    """Timeline from recorded timestamps only, so no time is ever made up."""
    incident = state["incident"]
    catalog = state.get("evidence", [])
    events = [
        TimelineEvent(timestamp=e.timestamp, description=e.summary, source=e.id)
        for e in catalog
        if e.timestamp is not None and e.kind in (EvidenceKind.DEPLOYMENT, EvidenceKind.CHANGE)
    ]
    logs = [(e.timestamp, e) for e in catalog if e.kind is EvidenceKind.LOG and e.timestamp]
    if logs:
        first_at, first = min(logs, key=lambda pair: pair[0])
        events.append(
            TimelineEvent(
                timestamp=first_at,
                description=f"First error observed: {first.summary}",
                source=first.id,
            )
        )
    events.append(
        TimelineEvent(
            timestamp=incident.timestamp,
            description=f"Alert fired: {incident.title}",
            source=incident.incident_id,
        )
    )
    decision = state.get("approval_decision")
    if decision is not None:
        verb = "approved" if decision.approved else "rejected"
        note = f": {decision.comment}" if decision.comment else ""
        events.append(
            TimelineEvent(
                timestamp=decision.decided_at,
                description=f"Remediation {verb} by {decision.decided_by}{note}",
                source=decision.approval_id,
            )
        )
    for action in state.get("tool_execution_result", []):
        events.append(
            TimelineEvent(
                timestamp=action.executed_at,
                description=f"{action.tool} {action.status}: {action.message}",
                source=decision.approval_id if decision else action.tool,
            )
        )
    return sorted(events, key=lambda e: e.timestamp)


def _outcome(state: IncidentState) -> str:
    decision = state.get("approval_decision")
    if decision is None:
        return "No production change needed approval."
    if not decision.approved:
        reason = f" ({decision.comment})" if decision.comment else ""
        return f"Rejected by {decision.decided_by}{reason}; no actions were executed."
    results = "; ".join(f"{a.tool} {a.status}" for a in state.get("tool_execution_result", []))
    return f"Approved by {decision.decided_by}. Executed: {results or 'nothing'}."


def heuristic_draft(state: IncidentState) -> PostmortemDraft:
    incident = state["incident"]
    selected = state["selected_root_cause"]
    plan = state["remediation_plan"]
    metrics = state.get("retrieved_metrics")
    triage = state.get("triage_summary")

    impact_parts = []
    if metrics is not None:
        for summary in metrics.anomalies():
            if summary.name in ("error_rate_pct", "p99_latency_ms", "requests_per_sec"):
                impact_parts.append(f"{summary.name} reached {summary.peak} {summary.unit}")
    impact = f"{incident.service} in {incident.environment} was affected" + (
        f": {', '.join(impact_parts)}." if impact_parts else "."
    )
    open_questions = list(state.get("data_gaps", []))
    review = state.get("critic_feedback")
    if state.get("unresolved_critic_issues") and review is not None:
        open_questions += [f"Unresolved critic issue: {issue}" for issue in review.issues]

    return PostmortemDraft(
        title=f"{incident.incident_id}: {incident.title}",
        summary=triage.summary if triage else incident.description,
        impact=impact,
        root_cause=f"{selected.title}. {selected.description}",
        remediation=plan.summary
        + " Steps: "
        + "; ".join(s.description for s in plan.steps if s.kind is not StepKind.PREVENTION)
        + " "
        + _outcome(state),
        prevention=[s.description for s in plan.steps if s.kind is StepKind.PREVENTION],
        open_questions=open_questions,
    )


def postmortem_prompt(state: IncidentState) -> str:
    incident = state["incident"]
    return "\n\n".join(
        [
            f"Incident {incident.incident_id}: {incident.title}\n{incident.description}",
            "Selected root cause: " + state["selected_root_cause"].model_dump_json(),
            "Remediation plan: " + state["remediation_plan"].model_dump_json(),
            "Critic review: "
            + (review.model_dump_json() if (review := state.get("critic_feedback")) else "none"),
            "Unresolved critic issues: " + str(bool(state.get("unresolved_critic_issues"))),
            "Approval outcome: " + _outcome(state),
            "Data gaps: " + ("; ".join(state.get("data_gaps", [])) or "none"),
            "Evidence:\n" + render(state.get("evidence", [])),
        ]
    )


def _mode(calls: list[AgentCall]) -> Literal["llm", "heuristic", "mixed"]:
    modes = {c.mode for c in calls}
    if modes == {"heuristic"}:
        return "heuristic"
    if modes == {"llm"}:
        return "llm"
    return "mixed"


async def postmortem_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    draft, call = await run_step(
        "postmortem",
        deps.llm,
        PostmortemDraft,
        prompts.POSTMORTEM,
        lambda: postmortem_prompt(state),
        lambda: heuristic_draft(state),
    )
    plan = state["remediation_plan"]
    selected = state["selected_root_cause"]
    approval = state.get("approval_status", ApprovalStatus.NOT_REQUIRED)
    cited = list(dict.fromkeys(selected.evidence_for + [e for s in plan.steps for e in s.evidence]))
    calls = [*state.get("agent_calls", []), call]

    report = FinalReport(
        run_id=state["run_id"],
        incident_id=state["incident"].incident_id,
        trace_id=state.get("trace_id"),
        triage=state.get("triage_summary"),
        postmortem=draft,
        timeline=build_timeline(state),
        selected_root_cause=selected,
        hypotheses=state.get("root_cause_hypotheses", [selected]),
        remediation_plan=plan,
        approval_status=approval,
        approval=state.get("approval_decision"),
        executed_actions=list(state.get("tool_execution_result", [])),
        critic_review=state.get("critic_feedback"),
        unresolved_critic_issues=bool(state.get("unresolved_critic_issues")),
        retries=state.get("retry_count", 0),
        data_gaps=list(state.get("data_gaps", [])),
        evidence=list(state.get("evidence", [])),
        evidence_ids_cited=cited,
        agent_calls=calls,
        tool_call_count=len(state.get("tool_calls", [])),
        mode=_mode(calls),
    )
    return {"final_report": report, "approval_status": approval, "agent_calls": [call]}
