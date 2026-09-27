from app.config import Settings
from retrieval.backend import InMemoryBackend, SearchBackend
from retrieval.elastic_client import ElasticBackend
from retrieval.embeddings import EmbeddingProvider, create_embedder
from retrieval.reranker import CrossEncoderReranker, Reranker


def create_search_backend(settings: Settings) -> SearchBackend:
    if settings.search_backend == "memory":
        return InMemoryBackend()
    return ElasticBackend(settings.elasticsearch_url, settings.elasticsearch_index)


def embedder_from_settings(settings: Settings) -> EmbeddingProvider:
    return create_embedder(settings.embedding_provider, settings.embedding_model)


def reranker_from_settings(settings: Settings) -> Reranker | None:
    return CrossEncoderReranker(settings.reranker_model) if settings.reranker_model else None
