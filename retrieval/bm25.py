import math
import re
from collections import Counter
from typing import Any

from retrieval.models import ScoredDocument, SearchDocument, SearchFilters

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in",
        "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
    }
)  # fmt: skip

# Title and tags are short and descriptive, so matches there count more.
FIELD_BOOSTS = {"title": 2.0, "tags": 1.5, "text": 1.0}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def build_bm25_query(query: str, filters: SearchFilters, size: int) -> dict[str, Any]:
    body = filters.to_es()
    body["bool"]["must"] = [
        {
            "multi_match": {
                "query": query,
                "fields": [f"{field}^{boost}" for field, boost in FIELD_BOOSTS.items()],
                "type": "best_fields",
                "tie_breaker": 0.3,
            }
        }
    ]
    return {"query": body, "size": size}


class BM25Index:
    """In-memory Okapi BM25 with the same k1/b defaults as Elasticsearch."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: list[SearchDocument] = []
        self._fields: list[dict[str, Counter[str]]] = []
        self._lengths: dict[str, list[int]] = {f: [] for f in FIELD_BOOSTS}
        self._df: dict[str, Counter[str]] = {f: Counter() for f in FIELD_BOOSTS}

    def add(self, doc: SearchDocument) -> None:
        values = {"title": doc.title, "tags": " ".join(doc.tags), "text": doc.text}
        per_field = {}
        for field, value in values.items():
            tokens = tokenize(value)
            counts = Counter(tokens)
            per_field[field] = counts
            self._lengths[field].append(len(tokens))
            self._df[field].update(counts.keys())
        self._docs.append(doc)
        self._fields.append(per_field)

    def __len__(self) -> int:
        return len(self._docs)

    def _field_score(self, field: str, i: int, terms: list[str]) -> float:
        n = len(self._docs)
        avg_len = (sum(self._lengths[field]) / n) or 1.0
        length = self._lengths[field][i]
        counts = self._fields[i][field]
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = self._df[field][term]
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            norm = tf + self.k1 * (1 - self.b + self.b * length / avg_len)
            score += idf * tf * (self.k1 + 1) / norm
        return score

    def search(self, query: str, filters: SearchFilters, k: int) -> list[ScoredDocument]:
        terms = tokenize(query)
        scored = []
        for i, doc in enumerate(self._docs):
            if not filters.matches(doc):
                continue
            # best_fields with tie_breaker, mirroring the Elasticsearch query.
            field_scores = [
                self._field_score(field, i, terms) * boost for field, boost in FIELD_BOOSTS.items()
            ]
            best = max(field_scores)
            score = best + 0.3 * (sum(field_scores) - best)
            if score > 0:
                scored.append(ScoredDocument(doc, score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]
