from typing import Any

import numpy as np

from retrieval.models import ScoredDocument, SearchDocument, SearchFilters


def build_knn_query(
    vector: list[float], filters: SearchFilters, k: int, num_candidates: int = 100
) -> dict[str, Any]:
    return {
        "knn": {
            "field": "embedding",
            "query_vector": vector,
            "k": k,
            "num_candidates": max(num_candidates, k),
            "filter": filters.to_es(),
        },
        "size": k,
    }


class VectorIndex:
    """Exact cosine search over normalized vectors. Fine for thousands of documents."""

    def __init__(self) -> None:
        self._docs: list[SearchDocument] = []
        self._matrix: np.ndarray | None = None

    def add(self, doc: SearchDocument) -> None:
        if doc.embedding is None:
            raise ValueError(f"document {doc.document_id} has no embedding")
        row = np.asarray(doc.embedding, dtype=np.float32)
        row /= np.linalg.norm(row) or 1.0
        self._matrix = row[None, :] if self._matrix is None else np.vstack([self._matrix, row])
        self._docs.append(doc)

    def search(self, vector: list[float], filters: SearchFilters, k: int) -> list[ScoredDocument]:
        if self._matrix is None:
            return []
        query = np.asarray(vector, dtype=np.float32)
        query /= np.linalg.norm(query) or 1.0
        similarities = self._matrix @ query
        order = np.argsort(-similarities)
        results = []
        for i in order:
            doc = self._docs[int(i)]
            if filters.matches(doc):
                # Same transform Elasticsearch applies for cosine: (1 + cos) / 2.
                results.append(ScoredDocument(doc, float((1 + similarities[i]) / 2)))
                if len(results) == k:
                    break
        return results
