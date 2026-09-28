import re
from typing import Any

from agents import prompts
from agents.common import try_tool
from agents.evidence import Evidence, EvidenceKind, add_evidence, render
from agents.llm import run_step
from agents.schemas import (
    Hypothesis,
    RemediationPlan,
    RemediationStep,
    Risk,
    StepKind,
    ToolAction,
)
from graph.state import AgentDeps, IncidentState
from tools.runbooks import RunbookDocument
from tools.tool_registry import ToolCallRecord, ToolRegistry

MAX_RUNBOOKS = 2
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
_PREVENTION = ("alert", "add ", " ci", "pipeline", "test", "review", "monitor", "validate")
_MITIGATION = (
    "restart", "roll back", "rollback", "revert", "turn", "disable", "scale", "rate limit",
    "shed", "terminate", "force", "restore", "set ", "move",
)  # fmt: skip
_RISK_ORDER = [Risk.LOW, Risk.MEDIUM, Risk.HIGH]


def runbooks_for(hypothesis: Hypothesis, catalog: list[Evidence]) -> list[str]:
    """Runbooks behind the selected hypothesis, most relevant first."""
    by_id = {e.id: e for e in catalog}
    ordered: list[str] = []
    for evidence_id in hypothesis.evidence_for:
        item = by_id.get(evidence_id)
        if item is None:
            continue
        if item.kind is EvidenceKind.RUNBOOK:
            candidates = [item.metadata.get("runbook_id")]
        elif item.kind is EvidenceKind.INCIDENT:
            candidates = list(item.metadata.get("runbook_ids", []))
        else:
            continue
        ordered += [r for r in candidates if r and r not in ordered]
    return ordered[:MAX_RUNBOOKS]


def _bullets(text: str) -> list[str]:
    items = []
    for line in text.splitlines():
        match = _BULLET.match(line)
        if match:
            items.append(match.group(1).replace("`", "").strip())
    return items


def _implicated_deployment(hypothesis: Hypothesis, catalog: list[Evidence]) -> str | None:
    """A rollback target only counts when the deploy is evidence *for* the hypothesis."""
    by_id = {e.id: e for e in catalog}
    for evidence_id in hypothesis.evidence_for:
        item = by_id.get(evidence_id)
        if item and item.kind is EvidenceKind.DEPLOYMENT:
            return str(item.metadata.get("deployment_id"))
    return None


def heuristic_plan(
    state: IncidentState, runbook: RunbookDocument | None, section_ids: dict[str, str]
) -> RemediationPlan:
    incident = state["incident"]
    hypothesis = state["selected_root_cause"]
    catalog = state.get("evidence", [])
    cited = hypothesis.evidence_for[:2]
    steps: list[RemediationStep] = []

    if runbook is None:
        return RemediationPlan(
            summary=f"No runbook found for '{hypothesis.title}'; escalate to the service owner.",
            steps=[
                RemediationStep(
                    description=f"Page the {incident.service} owning team with the evidence "
                    "collected so far.",
                    kind=StepKind.MITIGATION,
                    risk=Risk.LOW,
                    evidence=cited,
                )
            ],
            rollback_plan="No changes are made, so nothing needs rolling back.",
            overall_risk=Risk.LOW,
        )

    diagnostics = _bullets(runbook.sections.get("Diagnostic steps", ""))
    if diagnostics:
        steps.append(
            RemediationStep(
                description=diagnostics[0],
                kind=StepKind.DIAGNOSTIC,
                risk=Risk.LOW,
                evidence=[section_ids["Diagnostic steps"], *cited],
            )
        )

    rollback_target = _implicated_deployment(hypothesis, catalog)
    remediation_id = section_ids.get("Remediation")
    for text in _bullets(runbook.sections.get("Remediation", "")):
        lowered = f" {text.lower()}"
        action: ToolAction | None = None
        risk = Risk.LOW
        if "restart" in lowered and "restart_service" in runbook.actions:
            action = ToolAction(tool="restart_service", service=incident.service)
            risk = Risk.MEDIUM
        elif (
            ("roll back" in lowered or "rollback" in lowered)
            and "rollback_deployment" in runbook.actions
            and rollback_target
        ):
            action = ToolAction(
                tool="rollback_deployment", service=incident.service, deployment_id=rollback_target
            )
            risk = Risk.HIGH
        if action is not None or any(word in lowered for word in _MITIGATION):
            kind = StepKind.MITIGATION
        elif any(word in lowered for word in _PREVENTION):
            kind = StepKind.PREVENTION
        else:
            kind = StepKind.FIX
        steps.append(
            RemediationStep(
                description=text,
                kind=kind,
                risk=risk,
                action=action,
                evidence=[e for e in [remediation_id, *cited] if e],
            )
        )

    rollback = _bullets(runbook.sections.get("Rollback", ""))
    overall = max((s.risk for s in steps), key=_RISK_ORDER.index, default=Risk.LOW)
    return RemediationPlan(
        summary=f"Remediate '{hypothesis.title}' following runbook '{runbook.title}'.",
        steps=steps,
        rollback_plan=" ".join(rollback) or "Revert any change made during remediation.",
        overall_risk=overall,
    )


def remediation_prompt(state: IncidentState, runbooks: list[RunbookDocument]) -> str:
    incident = state["incident"]
    hypothesis = state["selected_root_cause"]
    sections = []
    for runbook in runbooks:
        for name in ("Remediation", "Rollback", "Risk notes"):
            if name in runbook.sections:
                sections.append(f"## {runbook.title} / {name}\n{runbook.sections[name]}")
    return "\n\n".join(
        [
            f"Service: {incident.service} ({incident.environment})",
            f"Selected root cause: {hypothesis.model_dump_json()}",
            "Runbook guidance:\n" + ("\n\n".join(sections) or "none found"),
            "Evidence:\n" + render(state.get("evidence", [])),
            "Available actions: restart_service(service), "
            "rollback_deployment(service, deployment_id).",
        ]
    )


def requires_approval(plan: RemediationPlan, registry: ToolRegistry) -> bool:
    return any(s.action and registry.get(s.action.tool).destructive for s in plan.steps)


async def remediation_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    hypothesis = state["selected_root_cause"]
    catalog = list(state.get("evidence", []))
    calls: list[ToolCallRecord] = []
    gaps: list[str] = []

    runbooks: list[RunbookDocument] = []
    section_ids: dict[str, str] = {}
    for runbook_id in runbooks_for(hypothesis, catalog):
        runbook = await try_tool(
            deps, "get_runbook", {"runbook_id": runbook_id}, RunbookDocument, calls, gaps
        )
        if runbook is None:
            continue
        runbooks.append(runbook)
        for name in ("Diagnostic steps", "Remediation", "Rollback"):
            if name in runbook.sections:
                catalog, item = add_evidence(
                    catalog,
                    EvidenceKind.RUNBOOK,
                    f"Runbook '{runbook.title}' / {name}: {runbook.sections[name][:300]}",
                    f"runbook:{runbook_id}#{name.lower().replace(' ', '-')}",
                    runbook_id=runbook_id,
                    section=name,
                )
                # Step citations point at the primary runbook.
                section_ids.setdefault(name, item.id)

    primary = runbooks[0] if runbooks else None
    plan_state: IncidentState = {**state, "evidence": catalog}
    plan, call = await run_step(
        "remediation",
        deps.llm,
        RemediationPlan,
        prompts.REMEDIATION,
        lambda: remediation_prompt(plan_state, runbooks),
        lambda: heuristic_plan(plan_state, primary, section_ids),
    )
    approval = requires_approval(plan, deps.tools)
    plan = plan.model_copy(update={"approval_required": approval})
    return {
        "remediation_plan": plan,
        "approval_required": approval,
        "evidence": catalog,
        "tool_calls": calls,
        "agent_calls": [call],
        "data_gaps": gaps,
    }
