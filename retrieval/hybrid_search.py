import asyncio
from collections.abc import Sequence

from core.enums import Environment, SourceType
from retrieval.backend import SearchBackend
from retrieval.embeddings import EmbeddingProvider
from retrieval.models import (
    Fusion,
    ScoredDocument,
    SearchDocument,
    SearchFilters,
    SearchHit,
    SearchMode,
)
from retrieval.reranker import Reranker

RRF_K = 60
EXCERPT_CHARS = 400


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    """score(d) = sum over rankings of 1 / (k + rank(d)), rank starting at 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def weighted_fusion(
    score_lists: Sequence[dict[str, float]], weights: Sequence[float]
) -> dict[str, float]:
    """Min-max normalize each list to [0, 1], then take the weighted sum."""
    fused: dict[str, float] = {}
    for scores, weight in zip(score_lists, weights, strict=True):
        if not scores:
            continue
        low, high = min(scores.values()), max(scores.values())
        span = (high - low) or 1.0
        for doc_id, score in scores.items():
            fused[doc_id] = fused.get(doc_id, 0.0) + weight * (score - low) / span
    return fused


def _excerpt(text: str) -> str:
    if len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


class HybridSearcher:
    def __init__(
        self,
        backend: SearchBackend,
        embedder: EmbeddingProvider,
        reranker: Reranker | None = None,
        vector_weight: float = 0.5,
    ) -> None:
        self.backend = backend
        self.embedder = embedder
        self.reranker = reranker
        self.vector_weight = vector_weight

    async def search(
        self,
        query: str,
        *,
        service: str | None = None,
        environment: Environment | None = None,
        source_types: Sequence[SourceType] | None = None,
        exclude_incident_ids: Sequence[str] = (),
        top_k: int = 5,
        mode: SearchMode = SearchMode.HYBRID,
        fusion: Fusion = Fusion.RRF,
        collapse: bool = True,
    ) -> list[SearchHit]:
        filters = SearchFilters(
            service=service,
            environment=environment,
            source_types=list(source_types) if source_types else None,
            exclude_incident_ids=list(exclude_incident_ids),
        )
        # Over-fetch so collapsing chunks per parent still leaves top_k results.
        candidates = max(top_k * 8, 40)

        lexical: list[ScoredDocument] = []
        semantic: list[ScoredDocument] = []
        if mode in (SearchMode.BM25, SearchMode.HYBRID):
            lexical = await self.backend.bm25(query, filters, candidates)
        if mode in (SearchMode.VECTOR, SearchMode.HYBRID):
            vector = await asyncio.to_thread(self.embedder.embed_query, query)
            semantic = await self.backend.knn(vector, filters, candidates)

        docs: dict[str, SearchDocument] = {}
        for scored in (*lexical, *semantic):
            docs.setdefault(scored.document.document_id, scored.document)
        bm25_rank = {s.document.document_id: i for i, s in enumerate(lexical, start=1)}
        vector_rank = {s.document.document_id: i for i, s in enumerate(semantic, start=1)}

        if mode is SearchMode.BM25:
            scores = {s.document.document_id: s.score for s in lexical}
        elif mode is SearchMode.VECTOR:
            scores = {s.document.document_id: s.score for s in semantic}
        elif fusion is Fusion.RRF:
            scores = reciprocal_rank_fusion([list(bm25_rank), list(vector_rank)])
        else:
            scores = weighted_fusion(
                [
                    {s.document.document_id: s.score for s in lexical},
                    {s.document.document_id: s.score for s in semantic},
                ],
                [1 - self.vector_weight, self.vector_weight],
            )

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        hits: list[SearchHit] = []
        seen_parents: set[str] = set()
        for doc_id, score in ranked:
            doc = docs[doc_id]
            if collapse and doc.parent_id in seen_parents:
                continue
            seen_parents.add(doc.parent_id)
            hits.append(
                SearchHit(
                    document_id=doc.document_id,
                    parent_id=doc.parent_id,
                    source_type=doc.source_type,
                    title=doc.title,
                    excerpt=_excerpt(doc.text),
                    score=round(score, 6),
                    service=doc.service,
                    incident_id=doc.incident_id,
                    metadata=doc.metadata,
                    bm25_rank=bm25_rank.get(doc_id),
                    vector_rank=vector_rank.get(doc_id),
                )
            )

        if self.reranker is not None:
            hits = await asyncio.to_thread(self.reranker.rerank, query, hits, docs)
        return hits[:top_k]
