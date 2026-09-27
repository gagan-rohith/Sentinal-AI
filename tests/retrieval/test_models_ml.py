"""Checks against the real local models. Skipped when the ml extra is not installed."""

import pytest

pytest.importorskip("sentence_transformers")

from retrieval.embeddings import SentenceTransformerEmbedder
from retrieval.models import SearchDocument, SearchHit
from retrieval.reranker import CrossEncoderReranker

pytestmark = pytest.mark.integration


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_minilm_embeddings_are_semantic() -> None:
    embedder = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    assert embedder.dimensions == 384
    query = embedder.embed_query("users are logged out after the signing key changed")
    related, unrelated = embedder.embed_documents(
        ["JWT verification failed: kid not found in JWKS", "Kafka consumer lag is growing"]
    )
    assert cosine(query, related) > cosine(query, unrelated)


def test_cross_encoder_reranks_by_relevance() -> None:
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    docs = {
        "a": SearchDocument(
            document_id="a",
            parent_id="a",
            source_type="runbook",
            title="a",
            text="Kafka consumer lag grows when batches exceed max.poll.interval.ms",
        ),
        "b": SearchDocument(
            document_id="b",
            parent_id="b",
            source_type="runbook",
            title="b",
            text="TLS certificate expired because cert-manager renewal failed",
        ),
    }
    hits = [
        SearchHit(
            document_id=d.document_id,
            parent_id=d.parent_id,
            source_type=d.source_type,
            title=d.title,
            excerpt=d.text,
            score=0.0,
            service=None,
            incident_id=None,
            metadata={},
        )
        for d in docs.values()
    ]
    ranked = reranker.rerank("certificate expired", hits, docs)
    assert [h.document_id for h in ranked] == ["b", "a"]
    assert reranker.rerank("anything", [], docs) == []
