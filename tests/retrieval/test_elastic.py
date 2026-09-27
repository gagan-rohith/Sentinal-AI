import os
import uuid
from collections.abc import AsyncIterator

import pytest

from core.enums import SourceType
from core.exceptions import SearchUnavailableError
from core.models import Incident
from retrieval.elastic_client import ElasticBackend, index_body
from retrieval.embeddings import HashEmbedder
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import ingest
from retrieval.models import SearchDocument, SearchFilters

ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")


def test_index_mapping_is_strict_with_cosine_vectors() -> None:
    mapping = index_body(384)["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["embedding"] == {
        "type": "dense_vector",
        "dims": 384,
        "index": True,
        "similarity": "cosine",
    }
    assert mapping["properties"]["metadata"]["enabled"] is False


async def test_unreachable_cluster_raises_typed_error() -> None:
    backend = ElasticBackend("http://127.0.0.1:1", "missing", timeout_s=0.5)
    try:
        assert await backend.ping() is False
        with pytest.raises(SearchUnavailableError, match="unreachable"):
            await backend.bm25("pool", SearchFilters(), 5)
    finally:
        await backend.close()


@pytest.fixture
async def elastic() -> AsyncIterator[ElasticBackend]:
    backend = ElasticBackend(ES_URL, f"sentinel-test-{uuid.uuid4().hex[:8]}")
    if not await backend.ping():
        await backend.close()
        pytest.skip(f"Elasticsearch not reachable at {ES_URL}")
    yield backend
    await backend.client.indices.delete(index=backend.index, ignore_unavailable=True)
    await backend.close()


@pytest.mark.integration
async def test_missing_index_raises_typed_error(elastic: ElasticBackend) -> None:
    assert await elastic.count() == 0
    with pytest.raises(SearchUnavailableError, match="does not exist"):
        await elastic.bm25("pool", SearchFilters(), 5)


@pytest.mark.integration
async def test_elasticsearch_hybrid_search_end_to_end(
    elastic: ElasticBackend, knowledge_docs: list[SearchDocument], demo_incident: Incident
) -> None:
    embedder = HashEmbedder()
    indexed = await ingest(elastic, embedder, knowledge_docs, recreate=True)
    assert indexed == len(knowledge_docs) == await elastic.count()

    searcher = HybridSearcher(elastic, embedder)
    runbooks = await searcher.search(
        demo_incident.search_text(), source_types=[SourceType.RUNBOOK], top_k=3
    )
    assert "runbook:postgres-connection-pool-exhaustion" in [h.parent_id for h in runbooks]
    assert any(h.bm25_rank and h.vector_rank for h in runbooks)

    similar = await searcher.search(
        demo_incident.search_text(),
        source_types=[SourceType.INCIDENT],
        service="checkout-api",
        exclude_incident_ids=[demo_incident.incident_id],
        top_k=5,
    )
    assert similar
    assert {h.service for h in similar} == {"checkout-api"}
    assert demo_incident.incident_id not in {h.incident_id for h in similar}
