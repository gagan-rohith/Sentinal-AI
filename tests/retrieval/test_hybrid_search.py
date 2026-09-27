from core.enums import SourceType
from core.models import Incident
from retrieval.hybrid_search import HybridSearcher
from retrieval.models import Fusion, SearchDocument, SearchHit, SearchMode


async def test_demo_incident_retrieves_postgres_runbook(
    searcher: HybridSearcher, demo_incident: Incident
) -> None:
    hits = await searcher.search(
        demo_incident.search_text(), source_types=[SourceType.RUNBOOK], top_k=3
    )
    assert "runbook:postgres-connection-pool-exhaustion" in [h.parent_id for h in hits]


async def test_similar_incidents_share_root_cause_category(
    searcher: HybridSearcher, demo_incident: Incident
) -> None:
    hits = await searcher.search(
        demo_incident.search_text(),
        source_types=[SourceType.INCIDENT],
        exclude_incident_ids=[demo_incident.incident_id],
        top_k=3,
    )
    assert hits[0].metadata["root_cause_category"] == demo_incident.root_cause_category
    assert demo_incident.incident_id not in {h.incident_id for h in hits}


async def test_collapse_returns_one_hit_per_parent(searcher: HybridSearcher) -> None:
    collapsed = await searcher.search("postgres connection pool", top_k=10)
    assert len({h.parent_id for h in collapsed}) == len(collapsed)

    expanded = await searcher.search("postgres connection pool", top_k=10, collapse=False)
    assert len({h.parent_id for h in expanded}) < len(expanded)


async def test_modes_report_component_ranks(searcher: HybridSearcher) -> None:
    query = "kafka consumer lag rebalance"
    bm25 = await searcher.search(query, mode=SearchMode.BM25)
    vector = await searcher.search(query, mode=SearchMode.VECTOR)
    hybrid = await searcher.search(query, mode=SearchMode.HYBRID)
    assert all(h.bm25_rank and h.vector_rank is None for h in bm25)
    assert all(h.vector_rank and h.bm25_rank is None for h in vector)
    assert any(h.bm25_rank and h.vector_rank for h in hybrid)
    assert hybrid[0].parent_id.startswith(("runbook:kafka", "incident:"))


async def test_weighted_fusion_mode(searcher: HybridSearcher) -> None:
    hits = await searcher.search("TLS certificate expired", fusion=Fusion.WEIGHTED, top_k=3)
    assert hits
    assert all(0 <= h.score <= 1 for h in hits)


async def test_service_filter_keeps_generic_runbooks(searcher: HybridSearcher) -> None:
    hits = await searcher.search("latency database", service="search-api", top_k=20)
    assert {h.service for h in hits} <= {None, "search-api"}
    assert any(h.source_type is SourceType.RUNBOOK for h in hits)


async def test_no_match_returns_empty(searcher: HybridSearcher) -> None:
    hits = await searcher.search("zzzqqq", mode=SearchMode.BM25)
    assert hits == []


async def test_reranker_reorders_results(searcher: HybridSearcher) -> None:
    received: list[SearchHit] = []

    class ReverseReranker:
        def rerank(
            self, query: str, hits: list[SearchHit], docs: dict[str, SearchDocument]
        ) -> list[SearchHit]:
            received.extend(hits)
            return list(reversed(hits))

    reranked_searcher = HybridSearcher(searcher.backend, searcher.embedder, ReverseReranker())
    reranked = await reranked_searcher.search("redis eviction", top_k=3)
    # The reranker sees the whole candidate pool, not just the top_k after fusion.
    assert len(received) > 3
    assert reranked == list(reversed(received))[:3]
