from typing import Any, Protocol

from retrieval.models import SearchDocument, SearchHit


class Reranker(Protocol):
    def rerank(
        self, query: str, hits: list[SearchHit], docs: dict[str, SearchDocument]
    ) -> list[SearchHit]: ...


class CrossEncoderReranker:
    """Rescores fused candidates with a cross-encoder. Slower, usually more precise."""

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("reranking needs the 'ml' extra (sentence-transformers)") from exc
        self._model: Any = CrossEncoder(model_name, device="cpu")

    def rerank(
        self, query: str, hits: list[SearchHit], docs: dict[str, SearchDocument]
    ) -> list[SearchHit]:
        if not hits:
            return hits
        pairs = [(query, docs[h.document_id].text) for h in hits]
        scores = self._model.predict(pairs)
        rescored = [
            h.model_copy(update={"score": round(float(s), 6)})
            for h, s in zip(hits, scores, strict=True)
        ]
        return sorted(rescored, key=lambda h: h.score, reverse=True)
