from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from elastic_transport import ConnectionError as TransportConnectionError
from elastic_transport import ConnectionTimeout
from elasticsearch import ApiError, AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from core.exceptions import SearchUnavailableError
from retrieval.bm25 import build_bm25_query
from retrieval.models import ScoredDocument, SearchDocument, SearchFilters
from retrieval.vector_search import build_knn_query

log = structlog.get_logger(__name__)


def index_body(dimensions: int) -> dict[str, Any]:
    text = {"type": "text", "analyzer": "english"}
    return {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "document_id": {"type": "keyword"},
                "parent_id": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "title": text,
                "text": text,
                "tags": {**text, "fields": {"raw": {"type": "keyword"}}},
                "service": {"type": "keyword"},
                "environment": {"type": "keyword"},
                "severity": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "incident_id": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": False},
                "embedding": {
                    "type": "dense_vector",
                    "dims": dimensions,
                    "index": True,
                    "similarity": "cosine",
                },
            },
        },
    }


class ElasticBackend:
    name = "elasticsearch"

    def __init__(self, url: str, index: str, timeout_s: float = 10.0) -> None:
        self.url = url
        self.index = index
        # One retry covers a transient blip; more would outlast the tool timeout when the
        # cluster is down and turn a clear "unavailable" error into a generic timeout.
        self.client = AsyncElasticsearch(
            url, request_timeout=timeout_s, retry_on_timeout=True, max_retries=1
        )

    @asynccontextmanager
    async def _guard(self, operation: str) -> AsyncIterator[None]:
        try:
            yield
        except (TransportConnectionError, ConnectionTimeout) as exc:
            raise SearchUnavailableError(
                f"Elasticsearch is unreachable at {self.url} during {operation}",
                details={"operation": operation},
            ) from exc
        except ApiError as exc:
            if exc.meta.status == 404:
                raise SearchUnavailableError(
                    f"index '{self.index}' does not exist; run python -m retrieval.indexing",
                    details={"operation": operation},
                ) from exc
            raise SearchUnavailableError(
                f"Elasticsearch returned {exc.meta.status} during {operation}: {exc.message}",
                details={"operation": operation, "status": exc.meta.status},
            ) from exc

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def ensure_index(self, dimensions: int, *, recreate: bool = False) -> None:
        async with self._guard("ensure_index"):
            exists = bool(await self.client.indices.exists(index=self.index))
            if exists and recreate:
                await self.client.indices.delete(index=self.index)
                exists = False
            if not exists:
                await self.client.indices.create(index=self.index, **index_body(dimensions))
                log.info("index_created", index=self.index, dimensions=dimensions)

    async def index_documents(self, docs: list[SearchDocument]) -> int:
        actions = (
            {
                "_index": self.index,
                "_id": doc.document_id,
                "_source": doc.model_dump(mode="json", exclude_none=True),
            }
            for doc in docs
        )
        async with self._guard("index_documents"):
            indexed, errors = await async_bulk(self.client, actions, raise_on_error=False)
            await self.client.indices.refresh(index=self.index)
        # With raise_on_error=False the second value is the list of per-document errors.
        if isinstance(errors, list) and errors:
            raise SearchUnavailableError(
                f"{len(errors)} documents failed to index", details={"first_error": errors[0]}
            )
        return int(indexed)

    async def count(self) -> int:
        async with self._guard("count"):
            if not await self.client.indices.exists(index=self.index):
                return 0
            response = await self.client.count(index=self.index)
        return int(response["count"])

    async def _search(self, body: dict[str, Any], operation: str) -> list[ScoredDocument]:
        async with self._guard(operation):
            response = await self.client.search(
                index=self.index, **body, source_excludes=["embedding"]
            )
        return [
            ScoredDocument(SearchDocument.model_validate(hit["_source"]), float(hit["_score"]))
            for hit in response["hits"]["hits"]
        ]

    async def bm25(self, query: str, filters: SearchFilters, k: int) -> list[ScoredDocument]:
        return await self._search(build_bm25_query(query, filters, k), "bm25")

    async def knn(
        self, vector: list[float], filters: SearchFilters, k: int
    ) -> list[ScoredDocument]:
        return await self._search(build_knn_query(vector, filters, k), "knn")

    async def close(self) -> None:
        await self.client.close()
