from retrieval.backend import InMemoryBackend
from retrieval.embeddings import HashEmbedder
from retrieval.indexing import INDEX_FORMAT_VERSION, ensure_current_index, index_signature
from retrieval.models import SearchDocument


class CountingDocs:
    def __init__(self, docs: list[SearchDocument]) -> None:
        self.docs = docs
        self.calls = 0

    def __call__(self) -> list[SearchDocument]:
        self.calls += 1
        return self.docs


async def test_builds_once_then_reuses(knowledge_docs: list[SearchDocument]) -> None:
    backend, embedder = InMemoryBackend(), HashEmbedder()
    docs = CountingDocs(knowledge_docs)

    assert await ensure_current_index(backend, embedder, docs) is True
    assert await backend.count() == len(knowledge_docs)
    assert await backend.signature() == index_signature(embedder)

    assert await ensure_current_index(backend, embedder, docs) is False
    assert docs.calls == 1


async def test_changed_embedder_forces_a_rebuild(knowledge_docs: list[SearchDocument]) -> None:
    backend = InMemoryBackend()
    docs = CountingDocs(knowledge_docs)
    await ensure_current_index(backend, HashEmbedder(dimensions=384), docs)

    assert await ensure_current_index(backend, HashEmbedder(dimensions=128), docs) is True
    signature = await backend.signature()
    assert signature is not None
    assert signature["dimensions"] == 128
    # Rebuilt from scratch, not appended to the old documents.
    assert await backend.count() == len(knowledge_docs)


async def test_index_without_signature_is_rebuilt(knowledge_docs: list[SearchDocument]) -> None:
    # Indexes built before signatures existed have none, and must be rebuilt.
    backend, embedder = InMemoryBackend(), HashEmbedder()
    await backend.index_documents(
        [d.model_copy(update={"embedding": [0.0] * 384}) for d in knowledge_docs[:3]]
    )
    assert await backend.signature() is None
    assert await ensure_current_index(backend, embedder, lambda: knowledge_docs) is True
    assert await backend.count() == len(knowledge_docs)


def test_signature_names_format_version_and_model() -> None:
    assert index_signature(HashEmbedder()) == {
        "format_version": INDEX_FORMAT_VERSION,
        "embedder": "hash",
        "dimensions": 384,
    }
