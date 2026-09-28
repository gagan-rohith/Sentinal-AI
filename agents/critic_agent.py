from typing import Any

from pydantic import ValidationError

from agents import prompts
from agents.evidence import EvidenceKind, evidence_ids, render
from agents.llm import run_step
from agents.schemas import CriticReview, CriticVerdict, StepKind
from core.exceptions import ToolNotFoundError
from graph.state import AgentDeps, IncidentState
from tools.tool_registry import ToolRegistry

MIN_ROOT_CAUSE_CONFIDENCE = 0.35
MIN_HYPOTHESES = 3

# Higher wins when code checks and the model disagree. Evidence problems come first
# because a better root cause or plan cannot be built on missing evidence.
SEVERITY = {
    CriticVerdict.APPROVE: 0,
    CriticVerdict.REVISE_REMEDIATION: 1,
    CriticVerdict.REVISE_ROOT_CAUSE: 2,
    CriticVerdict.NEED_MORE_EVIDENCE: 3,
}

Finding = tuple[CriticVerdict, str]


def code_checks(state: IncidentState, registry: ToolRegistry) -> list[Finding]:
    catalog = state.get("evidence", [])
    known = evidence_ids(catalog)
    hypotheses = state.get("root_cause_hypotheses", [])
    selected = state["selected_root_cause"]
    plan = state["remediation_plan"]
    findings: list[Finding] = []

    if not any(e.kind is EvidenceKind.RUNBOOK for e in catalog):
        findings.append((CriticVerdict.NEED_MORE_EVIDENCE, "no runbook evidence was retrieved"))
    if not selected.evidence_for:
        findings.append(
            (CriticVerdict.NEED_MORE_EVIDENCE, "selected root cause cites no supporting evidence")
        )
    if state.get("root_cause_confidence", 0.0) < MIN_ROOT_CAUSE_CONFIDENCE:
        findings.append(
            (
                CriticVerdict.NEED_MORE_EVIDENCE,
                f"root cause confidence {state.get('root_cause_confidence', 0.0):.2f} is below "
                f"{MIN_ROOT_CAUSE_CONFIDENCE}",
            )
        )

    for hypothesis in hypotheses:
        unknown = sorted(set(hypothesis.evidence_for + hypothesis.evidence_against) - known)
        if unknown:
            findings.append(
                (
                    CriticVerdict.REVISE_ROOT_CAUSE,
                    f"hypothesis '{hypothesis.title}' cites unknown evidence {', '.join(unknown)}",
                )
            )
    if len(selected.evidence_against) > len(selected.evidence_for):
        findings.append(
            (
                CriticVerdict.REVISE_ROOT_CAUSE,
                "selected root cause has more evidence against it than for it",
            )
        )
    if len(hypotheses) < MIN_HYPOTHESES:
        findings.append(
            (CriticVerdict.REVISE_ROOT_CAUSE, f"only {len(hypotheses)} hypotheses considered")
        )

    if not plan.steps:
        findings.append((CriticVerdict.REVISE_REMEDIATION, "remediation plan has no steps"))
    elif not any(s.kind in (StepKind.MITIGATION, StepKind.FIX) for s in plan.steps):
        findings.append(
            (CriticVerdict.REVISE_REMEDIATION, "remediation plan has no mitigation or fix step")
        )
    deployments = {
        e.metadata.get("deployment_id") for e in catalog if e.kind is EvidenceKind.DEPLOYMENT
    }
    for step in plan.steps:
        unknown = sorted(set(step.evidence) - known)
        if unknown:
            findings.append(
                (
                    CriticVerdict.REVISE_REMEDIATION,
                    f"step '{step.description[:60]}' cites unknown evidence {', '.join(unknown)}",
                )
            )
        if step.action is None:
            continue
        try:
            registry.get(step.action.tool).input_model.model_validate(step.action.arguments())
        except (ToolNotFoundError, ValidationError):
            findings.append(
                (
                    CriticVerdict.REVISE_REMEDIATION,
                    f"action {step.action.tool} has invalid arguments {step.action.arguments()}",
                )
            )
        if (
            step.action.tool == "rollback_deployment"
            and step.action.deployment_id not in deployments
        ):
            findings.append(
                (
                    CriticVerdict.REVISE_REMEDIATION,
                    f"rollback targets {step.action.deployment_id}, which is not in the evidence",
                )
            )
    return findings


def verdict_of(findings: list[Finding]) -> CriticVerdict:
    return max((v for v, _ in findings), key=SEVERITY.__getitem__, default=CriticVerdict.APPROVE)


def heuristic_review(findings: list[Finding], root_confidence: float) -> CriticReview:
    return CriticReview(
        verdict=verdict_of(findings),
        confidence=round(max(0.0, min(root_confidence, 1 - 0.25 * len(findings))), 2),
        issues=[message for _, message in findings],
    )


def critic_prompt(state: IncidentState, findings: list[Finding]) -> str:
    plan = state["remediation_plan"]
    return "\n\n".join(
        [
            "Automated check findings:\n"
            + ("\n".join(f"- {v}: {m}" for v, m in findings) or "- none"),
            "Selected root cause: " + state["selected_root_cause"].model_dump_json(),
            "Remediation plan: " + plan.model_dump_json(),
            "Evidence:\n" + render(state.get("evidence", [])),
        ]
    )


async def critic_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    findings = code_checks(state, deps.tools)
    confidence = state.get("root_cause_confidence", 0.0)
    review, call = await run_step(
        "critic",
        deps.llm,
        CriticReview,
        prompts.CRITIC,
        lambda: critic_prompt(state, findings),
        lambda: heuristic_review(findings, confidence),
    )
    # The model may be stricter than the code checks, never more lenient.
    code_verdict = verdict_of(findings)
    if SEVERITY[code_verdict] > SEVERITY[review.verdict]:
        review = review.model_copy(
            update={
                "verdict": code_verdict,
                "issues": [m for _, m in findings] + review.issues,
            }
        )

    retries = state.get("retry_count", 0)
    update: dict[str, Any] = {"critic_feedback": review, "agent_calls": [call]}
    if review.verdict is not CriticVerdict.APPROVE:
        if retries < deps.max_retries:
            update["retry_count"] = retries + 1
        else:
            update["unresolved_critic_issues"] = True
    return update
