"""End-to-end agent evaluation.

Each incident runs through the real graph in two settings:
- standard: the incident itself is hidden from similar-incident search
- holdout: every past incident of the same root cause category is hidden too, so the
  agents cannot copy a matching precedent and must work from runbooks and telemetry

Runs that pause for approval are rejected, so the benchmark never executes actions.
"""

import time
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from agents.remediation_agent import runbooks_for
from agents.schemas import ApprovalDecision
from core.enums import Role
from core.exceptions import SentinelError
from core.models import Incident
from evals.datasets import IncidentCase
from evals.evaluators import (
    CalibrationBin,
    brier_score,
    calibration_bins,
    cosine,
    expected_calibration_error,
    percentile,
)
from graph.checkpoint import serializer
from graph.incident_graph import RECURSION_LIMIT, build_incident_graph
from graph.state import AgentDeps, IncidentState, Stage
from observability.costs import estimate_cost
from retrieval.embeddings import EmbeddingProvider

Setting = Literal["standard", "holdout"]
SEMANTIC_MATCH_THRESHOLD = 0.6

BENCHMARK_REJECTION = ApprovalDecision(
    approval_id="apr-benchmark",
    approved=False,
    decided_by="benchmark",
    role=Role.OPERATOR,
    comment="benchmark runs never execute actions",
    decided_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class CaseResult(BaseModel):
    incident_id: str
    category: str
    setting: Setting
    error: str | None = None
    selected_title: str = ""
    selected_category: str | None = None
    selected_runbooks: list[str] = []
    confidence: float = 0.0
    category_correct: bool = False
    runbook_correct: bool = False
    semantic_similarity: float = 0.0
    citation_validity: float = 0.0
    unsupported_rate: float = 1.0
    correct_runbook_cited: bool = False
    approval_required: bool = False
    unresolved_critic_issues: bool = False
    retries: int = 0
    tool_calls: int = 0
    latency_ms: float = 0.0
    llm_calls: int = 0
    fallbacks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0


class SettingSummary(BaseModel):
    setting: Setting
    cases: int
    errors: int
    runbook_accuracy: float
    category_accuracy: float
    semantic_match_rate: float
    mean_semantic_similarity: float
    mean_confidence: float
    brier_score: float
    expected_calibration_error: float
    calibration: list[CalibrationBin]
    citation_validity: float
    unsupported_claim_rate: float
    correct_runbook_cited_rate: float
    approval_required_rate: float
    retry_rate: float
    mean_retries: float
    mean_tool_calls: float
    latency_ms_mean: float
    latency_ms_p95: float
    llm_calls: int
    fallbacks: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    runbook_accuracy_by_category: dict[str, float]
    misdiagnosed: list[str]


def grounding(state: dict[str, Any]) -> tuple[float, float]:
    """(share of citations that point at real evidence, share of claims with no citation)."""
    known = {e.id for e in state.get("evidence", [])}
    hypotheses = state.get("root_cause_hypotheses", [])
    plan = state.get("remediation_plan")
    steps = plan.steps if plan else []
    cited = [e for h in hypotheses for e in h.evidence_for + h.evidence_against]
    cited += [e for s in steps for e in s.evidence]
    validity = sum(1 for e in cited if e in known) / len(cited) if cited else 0.0
    unsupported = sum(1 for h in hypotheses if h.confidence > 0 and not h.evidence_for)
    unsupported += sum(1 for s in steps if not s.evidence)
    claims = len(hypotheses) + len(steps)
    return round(validity, 4), round(unsupported / claims, 4) if claims else 1.0


def _cited_runbooks(state: dict[str, Any]) -> set[str]:
    by_id = {e.id: e for e in state.get("evidence", [])}
    plan = state.get("remediation_plan")
    selected = state.get("selected_root_cause")
    cited = list(selected.evidence_for) if selected else []
    cited += [e for s in (plan.steps if plan else []) for e in s.evidence]
    return {
        str(by_id[e].metadata.get("runbook_id"))
        for e in cited
        if e in by_id and by_id[e].metadata.get("runbook_id")
    }


async def evaluate_case(
    deps: AgentDeps,
    embedder: EmbeddingProvider,
    case: IncidentCase,
    incident: Incident,
    setting: Setting,
    holdout: list[str],
) -> CaseResult:
    graph = build_incident_graph(deps, InMemorySaver(serde=serializer()))
    run_id = f"bench-{setting}-{case.incident_id}"
    config: Any = {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}
    initial: IncidentState = {
        "run_id": run_id,
        "incident": incident,
        "stage": Stage.START,
        "holdout_incident_ids": holdout,
    }
    base = {"incident_id": case.incident_id, "category": case.category, "setting": setting}
    started = time.perf_counter()
    try:
        await graph.ainvoke(initial, config)
        if (await graph.aget_state(config)).next:
            resume: Command[Any] = Command(resume=BENCHMARK_REJECTION.model_dump(mode="json"))
            await graph.ainvoke(resume, config)
    except SentinelError as exc:
        return CaseResult(**base, error=f"{exc.code}: {exc.message}")
    latency = round((time.perf_counter() - started) * 1000, 2)
    state: dict[str, Any] = dict((await graph.aget_state(config)).values)

    selected = state["selected_root_cause"]
    runbooks = runbooks_for(selected, state.get("evidence", []))
    expected, predicted = embedder.embed_documents(
        [case.expected_root_cause, f"{selected.title}. {selected.description}"]
    )
    validity, unsupported = grounding(state)
    calls = state.get("agent_calls", [])
    input_tokens = sum(c.input_tokens for c in calls)
    output_tokens = sum(c.output_tokens for c in calls)
    model = next((c.model for c in calls if c.mode == "llm"), None)
    return CaseResult(
        **base,
        selected_title=selected.title,
        selected_category=selected.category,
        selected_runbooks=runbooks,
        confidence=state.get("root_cause_confidence", selected.confidence),
        category_correct=selected.category == case.category,
        runbook_correct=bool(runbooks) and runbooks[0] in case.relevant_runbook_ids,
        semantic_similarity=round(cosine(expected, predicted), 4),
        citation_validity=validity,
        unsupported_rate=unsupported,
        correct_runbook_cited=bool(_cited_runbooks(state) & set(case.relevant_runbook_ids)),
        approval_required=bool(state.get("approval_required")),
        unresolved_critic_issues=bool(state.get("unresolved_critic_issues")),
        retries=state.get("retry_count", 0),
        tool_calls=len(state.get("tool_calls", [])),
        latency_ms=latency,
        llm_calls=sum(1 for c in calls if c.mode == "llm"),
        fallbacks=sum(1 for c in calls if c.mode == "fallback"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost(model, input_tokens, output_tokens),
    )


def summarize(setting: Setting, results: list[CaseResult]) -> SettingSummary:
    ok = [r for r in results if r.error is None]
    confidences = [r.confidence for r in ok]
    correct = [r.runbook_correct for r in ok]
    by_category: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r.error is None and r.runbook_correct)
    costs = [r.cost_usd for r in ok]

    def rate(values: list[bool]) -> float:
        return round(mean(values), 4) if values else 0.0

    def avg(values: list[float]) -> float:
        return round(mean(values), 4) if values else 0.0

    all_correct = [r.error is None and r.runbook_correct for r in results]
    return SettingSummary(
        setting=setting,
        cases=len(results),
        errors=len(results) - len(ok),
        runbook_accuracy=rate(all_correct),
        category_accuracy=rate([r.error is None and r.category_correct for r in results]),
        semantic_match_rate=rate(
            [r.error is None and r.semantic_similarity >= SEMANTIC_MATCH_THRESHOLD for r in results]
        ),
        mean_semantic_similarity=avg([r.semantic_similarity for r in ok]),
        mean_confidence=avg(confidences),
        brier_score=round(brier_score(confidences, correct), 4),
        expected_calibration_error=expected_calibration_error(confidences, correct),
        calibration=calibration_bins(confidences, correct),
        citation_validity=avg([r.citation_validity for r in ok]),
        unsupported_claim_rate=avg([r.unsupported_rate for r in ok]),
        correct_runbook_cited_rate=rate([r.correct_runbook_cited for r in ok]),
        approval_required_rate=rate([r.approval_required for r in ok]),
        retry_rate=rate([r.retries > 0 for r in ok]),
        mean_retries=avg([float(r.retries) for r in ok]),
        mean_tool_calls=avg([float(r.tool_calls) for r in ok]),
        latency_ms_mean=avg([r.latency_ms for r in ok]),
        latency_ms_p95=round(percentile([r.latency_ms for r in ok], 95), 2),
        llm_calls=sum(r.llm_calls for r in ok),
        fallbacks=sum(r.fallbacks for r in ok),
        input_tokens=sum(r.input_tokens for r in ok),
        output_tokens=sum(r.output_tokens for r in ok),
        cost_usd=None if any(c is None for c in costs) else round(sum(c or 0.0 for c in costs), 4),
        runbook_accuracy_by_category={
            category: rate(values) for category, values in sorted(by_category.items())
        },
        misdiagnosed=[
            r.incident_id for r in results if not (r.error is None and r.runbook_correct)
        ],
    )


async def evaluate_agents(
    deps: AgentDeps,
    embedder: EmbeddingProvider,
    incidents: dict[str, Incident],
    cases: list[IncidentCase],
) -> tuple[list[CaseResult], list[SettingSummary]]:
    # Built from every known incident, not just the selected cases, so a --limit run
    # cannot leak a same-category incident that happens to be outside the sample.
    same_category: dict[str, list[str]] = defaultdict(list)
    for incident in incidents.values():
        if incident.root_cause_category:
            same_category[incident.root_cause_category].append(incident.incident_id)

    results: list[CaseResult] = []
    summaries = []
    settings: tuple[Setting, ...] = ("standard", "holdout")
    for setting in settings:
        batch = []
        for case in cases:
            holdout = (
                [i for i in same_category[case.category] if i != case.incident_id]
                if setting == "holdout"
                else []
            )
            batch.append(
                await evaluate_case(
                    deps, embedder, case, incidents[case.incident_id], setting, holdout
                )
            )
        results += batch
        summaries.append(summarize(setting, batch))
    return results, summaries
