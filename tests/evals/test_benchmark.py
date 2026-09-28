import json
from pathlib import Path
from typing import Any

import pytest

from agents.schemas import SearchPlan
from app.config import Settings
from auth.permissions import AGENT_PRINCIPAL
from core.models import Incident
from evals.agent_eval import evaluate_agents, grounding
from evals.benchmark import run_benchmark
from evals.datasets import build_incident_cases, load_incident_cases, load_qa_cases
from evals.report import load_latest, render_markdown
from graph.state import AgentDeps
from retrieval.embeddings import HashEmbedder
from tests.agent.conftest import ScriptedLLM
from tools.tool_registry import ToolRegistry

DEMO_AND_BAD_DEPLOY = ["INC-1060", "INC-1010"]


def test_committed_dataset_matches_the_incidents(incidents: list[Incident]) -> None:
    assert load_incident_cases() == build_incident_cases(incidents)
    assert len(load_incident_cases()) >= 50


def test_qa_set_points_at_real_runbooks() -> None:
    from data.loader import load_runbooks

    runbooks = {r.runbook_id for r in load_runbooks()}
    qa = load_qa_cases()
    assert len(qa) >= 40
    assert len({q.id for q in qa}) == len(qa)
    assert all(set(q.relevant_runbook_ids) <= runbooks for q in qa)
    assert {r for q in qa for r in q.relevant_runbook_ids} == runbooks


def test_grounding_counts_invalid_and_missing_citations(demo_state: dict[str, Any]) -> None:
    validity, unsupported = grounding(demo_state)
    assert validity == 1.0
    assert unsupported == 0.0

    selected = demo_state["selected_root_cause"]
    broken = selected.model_copy(update={"evidence_for": ["E999"]})
    empty = selected.model_copy(update={"evidence_for": []})
    state = {**demo_state, "root_cause_hypotheses": [broken, empty]}
    validity, unsupported = grounding(state)
    assert validity < 1.0
    assert unsupported > 0.0


@pytest.fixture
def bench_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"eval_reports_dir": tmp_path / "reports"})


async def test_benchmark_writes_labelled_reports(bench_settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "reports"
    report = await run_benchmark(bench_settings, incident_ids=DEMO_AND_BAD_DEPLOY, out_dir=out)

    assert report.setup.llm_mode == "heuristic"
    assert report.setup.llm_model is None
    assert report.setup.search_backend == "memory"
    assert report.setup.embedder == "hash"
    assert report.setup.incident_cases == 2
    assert [m.mode for m in report.retrieval] == ["bm25", "vector", "hybrid"]
    assert [a.setting for a in report.agents] == ["standard", "holdout"]
    assert {c.incident_id for c in report.cases} == set(DEMO_AND_BAD_DEPLOY)

    standard = report.agents[0]
    assert standard.errors == 0
    assert standard.runbook_accuracy == 1.0
    assert standard.citation_validity == 1.0
    assert standard.llm_calls == 0
    assert standard.cost_usd == 0.0

    files = sorted(p.name for p in out.iterdir())
    assert "latest.json" in files
    assert "latest.md" in files
    assert load_latest(out) == report
    markdown = (out / "latest.md").read_text(encoding="utf-8")
    assert "deterministic heuristic agents, not from an LLM" in markdown
    assert "| Runbook accuracy |" in markdown


async def test_holdout_hides_every_same_category_incident(
    registry: ToolRegistry, incidents: list[Incident]
) -> None:
    by_id = {i.incident_id: i for i in incidents}
    cases = [c for c in load_incident_cases() if c.incident_id == "INC-1060"]
    deps = AgentDeps(registry, None, AGENT_PRINCIPAL)
    results, summaries = await evaluate_agents(deps, HashEmbedder(), by_id, cases)

    standard, holdout = results
    assert standard.selected_category == "postgres_pool_exhaustion"
    # With every pool exhaustion incident hidden, the answer cannot come from a precedent.
    assert holdout.selected_category != "postgres_pool_exhaustion"
    assert [s.setting for s in summaries] == ["standard", "holdout"]


async def test_llm_tokens_and_cost_are_counted(
    registry: ToolRegistry, incidents: list[Incident]
) -> None:
    llm = ScriptedLLM(SearchPlan=[SearchPlan(queries=["hikari connection pool exhausted"])])
    llm.model = "claude-sonnet-5"
    by_id = {i.incident_id: i for i in incidents}
    cases = [c for c in load_incident_cases() if c.incident_id == "INC-1060"]
    results, summaries = await evaluate_agents(
        AgentDeps(registry, llm, AGENT_PRINCIPAL), HashEmbedder(), by_id, cases
    )
    assert results[0].llm_calls == 1
    assert results[0].fallbacks >= 1
    assert results[0].input_tokens == 100
    assert results[0].cost_usd == pytest.approx((100 * 2 + 20 * 10) / 1_000_000)
    assert summaries[0].cost_usd == pytest.approx(results[0].cost_usd)


def test_provider_switch_builds_the_configured_claude_client(settings: Settings) -> None:
    from pydantic import SecretStr

    from agents.llm import AnthropicLLM
    from evals.benchmark import _llm

    assert _llm(settings, "heuristic") is None
    configured = settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-ant-test"), "llm_model": "claude-opus-5"}
    )
    llm = _llm(configured, "anthropic")
    assert isinstance(llm, AnthropicLLM)
    assert llm.model == "claude-opus-5"


def test_markdown_flags_unknown_prices(tmp_path: Path) -> None:
    from evals.report import BenchmarkReport

    raw = json.loads(
        '{"setup": {"started_at": "2026-09-28T00:00:00Z", "duration_s": 1, "git_commit": "abc",'
        ' "search_backend": "memory", "embedder": "hash", "llm_mode": "anthropic",'
        ' "llm_model": "claude-sonnet-5", "incident_cases": 0, "qa_queries": 0},'
        ' "retrieval": [], "agents": [], "cases": []}'
    )
    markdown = render_markdown(BenchmarkReport.model_validate(raw))
    assert "anthropic (`claude-sonnet-5`)" in markdown
    assert "heuristic agents, not from an LLM" not in markdown
