"""Retrieval quality for BM25, vector and hybrid search.

Two query sets:
- incident queries: each incident's own text, judged against its relevant runbooks
- QA queries: hand-written paraphrases that avoid the runbooks' wording

Similar-incident retrieval is scored as a hit when a retrieved past incident has the
same root cause category (the incident itself is always excluded).
"""

from statistics import mean

from pydantic import BaseModel

from core.enums import SourceType
from core.models import Incident
from evals.datasets import IncidentCase, QACase
from evals.evaluators import precision_at_k, recall_at_k, reciprocal_rank
from retrieval.hybrid_search import HybridSearcher
from retrieval.models import SearchMode

K_VALUES = (1, 3, 5)
TOP_K = 5


class RetrievalScores(BaseModel):
    queries: int
    recall_at: dict[int, float]
    precision_at_3: float
    mrr: float


class ModeResult(BaseModel):
    mode: SearchMode
    incident_queries: RetrievalScores
    qa_queries: RetrievalScores
    similar_incident_hit_at_3: float


class Judged(BaseModel):
    retrieved: list[str]
    relevant: list[str]


def score(judged: list[Judged]) -> RetrievalScores:
    if not judged:
        return RetrievalScores(queries=0, recall_at={k: 0.0 for k in K_VALUES},
                               precision_at_3=0.0, mrr=0.0)  # fmt: skip
    return RetrievalScores(
        queries=len(judged),
        recall_at={
            k: round(mean(recall_at_k(j.retrieved, j.relevant, k) for j in judged), 4)
            for k in K_VALUES
        },
        precision_at_3=round(mean(precision_at_k(j.retrieved, j.relevant, 3) for j in judged), 4),
        mrr=round(mean(reciprocal_rank(j.retrieved, j.relevant) for j in judged), 4),
    )


async def _runbook_ids(searcher: HybridSearcher, query: str, mode: SearchMode) -> list[str]:
    hits = await searcher.search(query, source_types=[SourceType.RUNBOOK], top_k=TOP_K, mode=mode)
    return [h.parent_id.removeprefix("runbook:") for h in hits]


async def evaluate_mode(
    searcher: HybridSearcher,
    mode: SearchMode,
    incidents: dict[str, Incident],
    cases: list[IncidentCase],
    qa: list[QACase],
) -> ModeResult:
    incident_judged = [
        Judged(
            retrieved=await _runbook_ids(searcher, incidents[c.incident_id].search_text(), mode),
            relevant=c.relevant_runbook_ids,
        )
        for c in cases
    ]
    qa_judged = [
        Judged(
            retrieved=await _runbook_ids(searcher, q.query, mode), relevant=q.relevant_runbook_ids
        )
        for q in qa
    ]

    categories = {c.incident_id: c.category for c in cases}
    hits = []
    for case in cases:
        found = await searcher.search(
            incidents[case.incident_id].search_text(),
            source_types=[SourceType.INCIDENT],
            exclude_incident_ids=[case.incident_id],
            top_k=3,
            mode=mode,
        )
        hits.append(
            any(
                h.metadata.get("root_cause_category", categories.get(h.incident_id or ""))
                == case.category
                for h in found
            )
        )

    return ModeResult(
        mode=mode,
        incident_queries=score(incident_judged),
        qa_queries=score(qa_judged),
        similar_incident_hit_at_3=round(mean(hits), 4) if hits else 0.0,
    )


async def evaluate_retrieval(
    searcher: HybridSearcher,
    incidents: dict[str, Incident],
    cases: list[IncidentCase],
    qa: list[QACase],
) -> list[ModeResult]:
    return [await evaluate_mode(searcher, mode, incidents, cases, qa) for mode in SearchMode]
