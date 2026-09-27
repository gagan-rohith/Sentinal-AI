from typing import Protocol

from retrieval.bm25 import BM25Index
from retrieval.models import ScoredDocument, SearchDocument, SearchFilters
from retrieval.vector_search import VectorIndex


class SearchBackend(Protocol):
    name: str

    async def ping(self) -> bool: ...

    async def ensure_index(self, dimensions: int, *, recreate: bool = False) -> None: ...

    async def index_documents(self, docs: list[SearchDocument]) -> int: ...

    async def count(self) -> int: ...

    async def bm25(self, query: str, filters: SearchFilters, k: int) -> list[ScoredDocument]: ...

    async def knn(
        self, vector: list[float], filters: SearchFilters, k: int
    ) -> list[ScoredDocument]: ...

    async def close(self) -> None: ...


class InMemoryBackend:
    """Search backend used by tests and by local runs without Elasticsearch."""

    name = "memory"

    def __init__(self) -> None:
        self._bm25 = BM25Index()
        self._vectors = VectorIndex()

    async def ping(self) -> bool:
        return True

    async def ensure_index(self, dimensions: int, *, recreate: bool = False) -> None:
        if recreate:
            self._bm25 = BM25Index()
            self._vectors = VectorIndex()

    async def index_documents(self, docs: list[SearchDocument]) -> int:
        for doc in docs:
            self._bm25.add(doc)
            self._vectors.add(doc)
        return len(docs)

    async def count(self) -> int:
        return len(self._bm25)

    async def bm25(self, query: str, filters: SearchFilters, k: int) -> list[ScoredDocument]:
        return self._bm25.search(query, filters, k)

    async def knn(
        self, vector: list[float], filters: SearchFilters, k: int
    ) -> list[ScoredDocument]:
        return self._vectors.search(vector, filters, k)

    async def close(self) -> None:
        return None
