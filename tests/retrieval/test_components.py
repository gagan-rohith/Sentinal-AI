import math

import pytest

from core.enums import Environment, SourceType
from retrieval.bm25 import BM25Index, build_bm25_query, tokenize
from retrieval.embeddings import HashEmbedder, create_embedder
from retrieval.models import SearchDocument, SearchFilters
from retrieval.vector_search import VectorIndex, build_knn_query


def doc(doc_id: str, text: str, **kwargs: object) -> SearchDocument:
    fields: dict[str, object] = {
        "document_id": doc_id,
        "parent_id": doc_id,
        "source_type": SourceType.RUNBOOK,
        "title": doc_id,
        "text": text,
    }
    fields.update(kwargs)
    return SearchDocument.model_validate(fields)


def test_tokenize_lowercases_and_drops_stopwords() -> None:
    assert tokenize("The Pool IS exhausted, 503!") == ["pool", "exhausted", "503"]


def test_filters_treat_missing_service_as_generic() -> None:
    generic = doc("runbook", "x")
    checkout = doc("inc", "x", service="checkout-api", source_type=SourceType.INCIDENT)
    other = doc("other", "x", service="search-api", source_type=SourceType.INCIDENT)
    filters = SearchFilters(service="checkout-api")
    assert filters.matches(generic)
    assert filters.matches(checkout)
    assert not filters.matches(other)


def test_filters_on_environment_source_and_exclusions() -> None:
    staging = doc("s", "x", environment=Environment.STAGING, incident_id="INC-1001")
    assert not SearchFilters(environment=Environment.PRODUCTION).matches(staging)
    assert not SearchFilters(source_types=[SourceType.INCIDENT]).matches(staging)
    assert not SearchFilters(exclude_incident_ids=["INC-1001"]).matches(staging)
    assert SearchFilters(exclude_incident_ids=["INC-2000"]).matches(staging)


def test_filters_to_es_structure() -> None:
    body = SearchFilters(
        service="checkout-api",
        source_types=[SourceType.RUNBOOK],
        exclude_incident_ids=["INC-1060"],
    ).to_es()["bool"]
    service_clause = body["filter"][0]["bool"]["should"]
    assert {"term": {"service": "checkout-api"}} in service_clause
    assert {"terms": {"source_type": ["runbook"]}} in body["filter"]
    assert body["must_not"] == [{"terms": {"incident_id": ["INC-1060"]}}]


def test_empty_filters_produce_no_clauses() -> None:
    assert SearchFilters().to_es() == {"bool": {"filter": [], "must_not": []}}


def test_query_builders() -> None:
    bm25 = build_bm25_query("pool exhausted", SearchFilters(), 10)
    assert bm25["size"] == 10
    assert bm25["query"]["bool"]["must"][0]["multi_match"]["query"] == "pool exhausted"

    knn = build_knn_query([0.1, 0.2], SearchFilters(), k=5, num_candidates=2)
    assert knn["knn"]["k"] == 5
    assert knn["knn"]["num_candidates"] == 5  # never below k


def test_bm25_ranks_rare_matching_terms_first() -> None:
    index = BM25Index()
    for d in [
        doc("pool", "connection pool exhausted database"),
        doc("oom", "container memory oom killed"),
        doc("generic", "database database database latency"),
    ]:
        index.add(d)
    results = index.search("connection pool", SearchFilters(), k=3)
    assert [r.document.document_id for r in results] == ["pool"]


def test_bm25_title_boost() -> None:
    index = BM25Index()
    index.add(doc("in-title", "unrelated words here", title="redis eviction"))
    index.add(doc("in-text", "redis eviction happens", title="cache notes"))
    results = index.search("redis eviction", SearchFilters(), k=2)
    assert results[0].document.document_id == "in-title"


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashEmbedder(dimensions=64)
    a = embedder.embed_query("connection pool exhausted")
    assert a == embedder.embed_documents(["connection pool exhausted"])[0]
    assert len(a) == 64
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-6)


def test_hash_embedder_similarity_tracks_overlap() -> None:
    embedder = HashEmbedder()
    query = embedder.embed_query("postgres connection pool exhausted")
    close = embedder.embed_query("connection pool exhausted on postgres")
    far = embedder.embed_query("tls certificate expired")

    def cosine(x: list[float], y: list[float]) -> float:
        return sum(a * b for a, b in zip(x, y, strict=True))

    assert cosine(query, close) > cosine(query, far)


def test_vector_index_scores_and_filters() -> None:
    embedder = HashEmbedder()
    index = VectorIndex()
    for d in [doc("a", "disk pressure eviction"), doc("b", "kafka consumer lag")]:
        index.add(d.model_copy(update={"embedding": embedder.embed_query(d.text)}))
    results = index.search(embedder.embed_query("kafka lag"), SearchFilters(), k=2)
    assert results[0].document.document_id == "b"
    assert 0.0 <= results[1].score <= results[0].score <= 1.0


def test_vector_index_requires_embeddings() -> None:
    with pytest.raises(ValueError, match="no embedding"):
        VectorIndex().add(doc("a", "x"))
    assert VectorIndex().search([1.0], SearchFilters(), k=1) == []


def test_create_embedder_rejects_unknown_provider() -> None:
    assert create_embedder("hash", "unused").name == "hash"
    with pytest.raises(ValueError, match="unknown embedding provider"):
        create_embedder("nope", "unused")
