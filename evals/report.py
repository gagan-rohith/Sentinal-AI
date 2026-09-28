import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from evals.agent_eval import CaseResult, SettingSummary
from evals.retrieval_eval import ModeResult


class BenchmarkSetup(BaseModel):
    started_at: datetime
    duration_s: float
    git_commit: str
    search_backend: str
    embedder: str
    llm_mode: str
    llm_model: str | None
    incident_cases: int
    qa_queries: int


class BenchmarkReport(BaseModel):
    setup: BenchmarkSetup
    retrieval: list[ModeResult]
    agents: list[SettingSummary]
    cases: list[CaseResult]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(report: BenchmarkReport) -> str:
    s = report.setup
    lines = [
        "# SentinelAI benchmark",
        "",
        f"Generated {s.started_at:%Y-%m-%d %H:%M UTC} in {s.duration_s:.0f}s "
        f"at commit `{s.git_commit}`.",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Agents | {s.llm_mode}" + (f" (`{s.llm_model}`)" if s.llm_model else "") + " |",
        f"| Search backend | {s.search_backend} |",
        f"| Embeddings | `{s.embedder}` |",
        f"| Incident cases | {s.incident_cases} |",
        f"| QA queries | {s.qa_queries} |",
        "",
    ]
    if s.llm_mode == "heuristic":
        lines += [
            "> These numbers come from the deterministic heuristic agents, not from an LLM.",
            "",
        ]

    if report.retrieval:
        lines += [
            "## Retrieval",
            "",
            "Runbook retrieval, top 5 after collapsing sections into their runbook.",
            "",
            "| Mode | Queries | Recall@1 | Recall@3 | Recall@5 | Precision@3 | MRR |"
            " Similar incident hit@3 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for m in report.retrieval:
            for label, scores in (("incident", m.incident_queries), ("QA", m.qa_queries)):
                similar = _pct(m.similar_incident_hit_at_3) if label == "incident" else ""
                lines.append(
                    f"| {m.mode} | {label} ({scores.queries}) | {_pct(scores.recall_at[1])} | "
                    f"{_pct(scores.recall_at[3])} | {_pct(scores.recall_at[5])} | "
                    f"{_pct(scores.precision_at_3)} | {scores.mrr:.3f} | {similar} |"
                )
        lines.append("")

    if report.agents:
        by = {a.setting: a for a in report.agents}
        order = [by[k] for k in ("standard", "holdout") if k in by]
        header = "| Metric | " + " | ".join(a.setting for a in order) + " |"
        rows: list[tuple[str, Callable[[SettingSummary], str]]] = [
            ("Cases", lambda a: str(a.cases)),
            ("Errors", lambda a: str(a.errors)),
            ("Runbook accuracy", lambda a: _pct(a.runbook_accuracy)),
            ("Category accuracy", lambda a: _pct(a.category_accuracy)),
            ("Semantic match rate", lambda a: _pct(a.semantic_match_rate)),
            ("Mean semantic similarity", lambda a: f"{a.mean_semantic_similarity:.3f}"),
            ("Mean confidence", lambda a: f"{a.mean_confidence:.2f}"),
            ("Brier score (lower is better)", lambda a: f"{a.brier_score:.3f}"),
            ("Expected calibration error", lambda a: f"{a.expected_calibration_error:.3f}"),
            ("Citation validity", lambda a: _pct(a.citation_validity)),
            ("Unsupported claim rate", lambda a: _pct(a.unsupported_claim_rate)),
            ("Correct runbook cited", lambda a: _pct(a.correct_runbook_cited_rate)),
            ("Approval required", lambda a: _pct(a.approval_required_rate)),
            ("Runs with critic retries", lambda a: _pct(a.retry_rate)),
            ("Mean tool calls", lambda a: f"{a.mean_tool_calls:.1f}"),
            ("Latency mean / p95 (ms)",
             lambda a: f"{a.latency_ms_mean:.0f} / {a.latency_ms_p95:.0f}"),
            ("LLM calls / fallbacks", lambda a: f"{a.llm_calls} / {a.fallbacks}"),
            ("Tokens in / out", lambda a: f"{a.input_tokens} / {a.output_tokens}"),
            ("Estimated cost (USD)",
             lambda a: "unknown model price" if a.cost_usd is None else f"{a.cost_usd:.2f}"),
        ]  # fmt: skip
        lines += [
            "## Agents",
            "",
            "- **standard**: the incident itself is hidden from similar-incident search.",
            "- **holdout**: every past incident with the same root cause category is hidden too,"
            " so the agents cannot copy a matching precedent.",
            "",
            header,
            "|---|" + "---|" * len(order),
        ]
        lines += [f"| {name} | " + " | ".join(fn(a) for a in order) + " |" for name, fn in rows]
        lines += [
            "",
            "### Runbook accuracy by category",
            "",
            "| Category | " + " | ".join(a.setting for a in order) + " |",
            "|---|" + "---|" * len(order),
        ]
        categories = sorted({c for a in order for c in a.runbook_accuracy_by_category})
        for category in categories:
            values = [_pct(a.runbook_accuracy_by_category.get(category, 0.0)) for a in order]
            lines.append(f"| {category} | " + " | ".join(values) + " |")
        lines.append("")
        for a in order:
            if a.misdiagnosed:
                lines.append(f"Misdiagnosed ({a.setting}): {', '.join(a.misdiagnosed)}")
        lines += [
            "",
            "## How to read this",
            "",
            "- **Runbook accuracy**: the runbook behind the selected root cause is one of the"
            " incident's relevant runbooks. It is the headline metric because it applies whether"
            " a hypothesis came from a past incident, a runbook or an LLM.",
            "- **Category accuracy**: the selected hypothesis carries the exact category label."
            " Hypotheses built from runbooks have no label, so this undercounts in holdout.",
            f"- **Semantic match**: embedding cosine similarity between the selected root cause"
            f" and the ground truth is at least 0.6 ({s.embedder}).",
            "- **Citation validity**: share of cited evidence ids that exist in the run's"
            " evidence catalog. **Unsupported claim rate**: hypotheses with non-zero confidence"
            " and remediation steps that cite nothing.",
            "- The dataset is synthetic: 20 failure types with 3 variants each. The standard"
            " setting always has two close siblings in the index, which is why holdout is the"
            " more honest measure of reasoning.",
            "",
        ]
    return "\n".join(lines)


def write_report(report: BenchmarkReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.setup.started_at.strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"benchmark-{stamp}.json"
    md_path = out_dir / f"benchmark-{stamp}.md"
    payload = json.dumps(report.model_dump(mode="json"), indent=2) + "\n"
    markdown = render_markdown(report)
    json_path.write_text(payload, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    (out_dir / "latest.json").write_text(payload, encoding="utf-8")
    (out_dir / "latest.md").write_text(markdown, encoding="utf-8")
    return json_path, md_path


def load_latest(out_dir: Path) -> BenchmarkReport | None:
    path = out_dir / "latest.json"
    if not path.exists():
        return None
    return BenchmarkReport.model_validate_json(path.read_text(encoding="utf-8"))
