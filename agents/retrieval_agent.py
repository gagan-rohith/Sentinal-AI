from typing import Any

from agents import prompts
from agents.common import try_tool
from agents.evidence import Evidence, EvidenceKind, add_evidence, render
from agents.llm import run_step
from agents.schemas import SearchPlan
from core.enums import SourceType
from graph.state import AgentDeps, IncidentState
from retrieval.models import SearchHit
from tools.search import SearchResults
from tools.tool_registry import ToolCallRecord

MAX_QUERIES = 3


def heuristic_plan(state: IncidentState) -> SearchPlan:
    incident = state["incident"]
    errors = (
        [p.example for p in state["retrieved_logs"].top_errors[:2]]
        if state.get("retrieved_logs")
        else list(incident.error_messages[:2])
    )
    anomalies = (
        [s.name.replace("_", " ") for s in state["retrieved_metrics"].anomalies()]
        if state.get("retrieved_metrics")
        else []
    )
    subsystem = state["triage_summary"].subsystem.value if state.get("triage_summary") else ""
    queries = [
        " ".join([incident.title, *errors]),
        " ".join([subsystem, *anomalies, *incident.symptoms[:2]]).strip(),
    ]
    return SearchPlan(queries=[q for q in queries if q])


def retrieval_prompt(state: IncidentState) -> str:
    incident = state["incident"]
    triage = state.get("triage_summary")
    return "\n\n".join(
        [
            f"Incident: {incident.title}\n{incident.description}",
            f"Triage: {triage.model_dump_json() if triage else 'not available'}",
            "Collected evidence:\n" + render(state.get("evidence", [])),
        ]
    )


def _add_hits(catalog: list[Evidence], hits: list[SearchHit], kind: EvidenceKind) -> list[Evidence]:
    for rank, hit in enumerate(hits, start=1):
        if kind is EvidenceKind.INCIDENT:
            summary = (
                f"Past incident {hit.incident_id} ({hit.metadata.get('root_cause_category')}): "
                f"{hit.title}. Root cause: {hit.metadata.get('root_cause')}"
            )
        elif kind is EvidenceKind.RUNBOOK:
            summary = f"Runbook section '{hit.title}': {hit.excerpt}"
        else:
            summary = f"{hit.title}: {hit.excerpt}"
        catalog, _ = add_evidence(catalog, kind, summary, hit.parent_id, rank=rank, **hit.metadata)
    return catalog


def _merge(existing: list[SearchHit], new: list[SearchHit]) -> list[SearchHit]:
    seen = {h.parent_id for h in existing}
    return existing + [h for h in new if h.parent_id not in seen]


async def retrieval_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    incident = state["incident"]
    plan, call = await run_step(
        "retrieval",
        deps.llm,
        SearchPlan,
        prompts.RETRIEVAL,
        lambda: retrieval_prompt(state),
        lambda: heuristic_plan(state),
    )
    queries = [q for q in plan.queries if len(q.strip()) >= 3][:MAX_QUERIES]
    if not queries:
        queries = heuristic_plan(state).queries

    # A retry means the critic wanted more evidence, so widen the search.
    top_k = 3 if state.get("retry_count", 0) == 0 else 5
    calls: list[ToolCallRecord] = []
    gaps: list[str] = []

    runbooks = list(state.get("retrieved_runbooks", []))
    for query in queries:
        found = await try_tool(
            deps, "search_runbooks", {"query": query, "top_k": top_k}, SearchResults, calls, gaps
        )
        if found:
            runbooks = _merge(runbooks, found.hits)

    similar_query = incident.search_text() if len(incident.search_text()) >= 3 else queries[0]
    similar = await try_tool(
        deps,
        "search_similar_incidents",
        {
            "query": similar_query,
            "top_k": top_k,
            "exclude_incident_ids": [incident.incident_id, *state.get("holdout_incident_ids", [])],
        },
        SearchResults,
        calls,
        gaps,
    )
    docs = await try_tool(
        deps,
        "search_knowledge",
        {
            "query": incident.title,
            "service": incident.service,
            "source_types": [SourceType.SERVICE_DOC],
            "top_k": 1,
        },
        SearchResults,
        calls,
        gaps,
    )

    similar_hits = _merge(list(state.get("similar_incidents", [])), similar.hits if similar else [])
    doc_hits = docs.hits if docs else []
    if not runbooks:
        gaps.append("no runbooks matched the incident")

    catalog = list(state.get("evidence", []))
    catalog = _add_hits(catalog, runbooks, EvidenceKind.RUNBOOK)
    catalog = _add_hits(catalog, similar_hits, EvidenceKind.INCIDENT)
    catalog = _add_hits(catalog, doc_hits, EvidenceKind.SERVICE_DOC)

    return {
        "search_queries": queries,
        "retrieved_runbooks": runbooks,
        "similar_incidents": similar_hits,
        "service_docs": doc_hits,
        "evidence": catalog,
        "tool_calls": calls,
        "agent_calls": [call],
        "data_gaps": gaps,
    }
