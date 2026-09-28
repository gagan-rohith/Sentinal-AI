from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agents import prompts
from agents.common import first_sentence, keywords
from agents.evidence import Evidence, EvidenceKind, render
from agents.llm import run_step
from agents.schemas import Hypothesis, RootCauseAnalysis
from graph.state import AgentDeps, IncidentState

MAX_HYPOTHESES = 5
MIN_HYPOTHESES = 3
MIN_KEYWORD_OVERLAP = 2
# A deploy that lands this close before the first error is a plausible trigger.
DEPLOY_SUSPECT_WINDOW = timedelta(minutes=30)
BAD_DEPLOYMENT = "bad_deployment"
TELEMETRY = {EvidenceKind.LOG, EvidenceKind.METRIC, EvidenceKind.HEALTH, EvidenceKind.CHANGE}


@dataclass
class _Candidate:
    title: str
    description: str
    category: str | None
    terms: set[str]
    runbook_ids: set[str] = field(default_factory=set)
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    score: float = 0.0

    def support(self, evidence_id: str, weight: float) -> None:
        if evidence_id not in self.evidence_for:
            self.evidence_for.append(evidence_id)
            self.score += weight


def _first_error_time(catalog: list[Evidence]) -> datetime | None:
    times = [e.timestamp for e in catalog if e.kind is EvidenceKind.LOG and e.timestamp]
    return min(times, default=None)


def heuristic_root_cause(state: IncidentState) -> RootCauseAnalysis:
    catalog = state.get("evidence", [])
    candidates: dict[str, _Candidate] = {}

    # 1. Past incidents with the same failure mode are the strongest prior.
    incidents = [e for e in catalog if e.kind is EvidenceKind.INCIDENT]
    for rank, item in enumerate(incidents, start=1):
        category = item.metadata.get("root_cause_category") or item.source
        root_cause = str(item.metadata.get("root_cause") or item.summary)
        candidate = candidates.get(category)
        if candidate is None:
            candidate = candidates[category] = _Candidate(
                title=first_sentence(root_cause),
                description=f"Same failure mode as {item.metadata.get('incident_id')}: "
                f"{root_cause}",
                category=category,
                terms=keywords(root_cause),
                runbook_ids=set(item.metadata.get("runbook_ids", [])),
            )
        candidate.support(item.id, 3.0 / rank)

    # 2. Runbooks either back an existing candidate or become their own hypothesis.
    runbooks = [e for e in catalog if e.kind is EvidenceKind.RUNBOOK]
    for rank, item in enumerate(runbooks, start=1):
        runbook_id = item.metadata.get("runbook_id", "")
        owner = next((c for c in candidates.values() if runbook_id in c.runbook_ids), None)
        if owner is None:
            title = item.summary.split("'")[1].split(":")[0] if "'" in item.summary else runbook_id
            owner = candidates[f"runbook:{runbook_id}"] = _Candidate(
                title=title,
                description=f"Failure described by runbook '{title}'.",
                category=None,
                terms=keywords(item.summary),
                runbook_ids={runbook_id},
            )
        owner.support(item.id, 2.0 / rank)

    # 3. Live telemetry that shares vocabulary with a candidate supports it.
    for candidate in candidates.values():
        for item in catalog:
            if item.kind in TELEMETRY:
                overlap = candidate.terms & keywords(item.summary)
                if len(overlap) >= MIN_KEYWORD_OVERLAP:
                    candidate.support(item.id, 1.0)

    # 4. Recent deployments are always considered, then kept or ruled out on timing.
    deploys = [
        (e.timestamp, e) for e in catalog if e.kind is EvidenceKind.DEPLOYMENT and e.timestamp
    ]
    if deploys:
        deployed_at, latest = max(deploys, key=lambda pair: pair[0])
        first_error = _first_error_time(catalog)
        candidate = candidates.get(BAD_DEPLOYMENT) or _Candidate(
            title=f"Regression introduced by deployment {latest.metadata.get('deployment_id')}",
            description=f"The most recent change to the service. {latest.summary}",
            category=BAD_DEPLOYMENT,
            terms=keywords(latest.summary),
        )
        candidates[BAD_DEPLOYMENT] = candidate
        if first_error and timedelta(0) <= first_error - deployed_at <= DEPLOY_SUSPECT_WINDOW:
            candidate.support(latest.id, 3.0)
        else:
            if latest.id not in candidate.evidence_against:
                candidate.evidence_against.append(latest.id)
            candidate.score *= 0.3
            candidate.description += (
                " Ruled out as the trigger: errors did not start within "
                f"{int(DEPLOY_SUSPECT_WINDOW.total_seconds() // 60)} minutes of the deploy."
            )

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:MAX_HYPOTHESES]
    while len(ranked) < MIN_HYPOTHESES:
        ranked.append(
            _Candidate(
                title="Unidentified infrastructure or dependency failure",
                description="No specific evidence; kept as a fallback hypothesis.",
                category=None,
                terms=set(),
            )
        )
    total = sum(c.score for c in ranked) or 1.0
    hypotheses = [
        Hypothesis(
            title=c.title,
            description=c.description,
            category=c.category,
            evidence_for=c.evidence_for,
            evidence_against=c.evidence_against,
            confidence=round(c.score / total, 2),
        )
        for c in ranked
    ]
    return RootCauseAnalysis(
        hypotheses=hypotheses,
        selected_index=0,
        reasoning=(
            "Candidates come from similar past incidents and runbooks, scored by retrieval "
            "rank and by how much of the live telemetry they explain."
        ),
    )


def root_cause_prompt(state: IncidentState) -> str:
    incident = state["incident"]
    triage = state.get("triage_summary")
    return "\n\n".join(
        [
            f"Incident {incident.incident_id}: {incident.title}\n{incident.description}",
            f"Triage: {triage.model_dump_json() if triage else 'not available'}",
            "Evidence:\n" + render(state.get("evidence", [])),
            "Data gaps: " + ("; ".join(state.get("data_gaps", [])) or "none"),
            _critic_note(state),
        ]
    )


def _critic_note(state: IncidentState) -> str:
    review = state.get("critic_feedback")
    if review is None:
        return "This is the first analysis."
    return "The critic rejected the previous analysis:\n- " + "\n- ".join(review.issues)


async def root_cause_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    analysis, call = await run_step(
        "root_cause",
        deps.llm,
        RootCauseAnalysis,
        prompts.ROOT_CAUSE,
        lambda: root_cause_prompt(state),
        lambda: heuristic_root_cause(state),
    )
    if not analysis.hypotheses:
        analysis = heuristic_root_cause(state)
    selected = analysis.selected
    return {
        "root_cause_hypotheses": analysis.hypotheses,
        "selected_root_cause": selected,
        "root_cause_confidence": selected.confidence,
        "agent_calls": [call],
    }
