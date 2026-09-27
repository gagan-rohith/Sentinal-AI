from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from core.enums import Environment, Severity, SourceType


class SearchMode(StrEnum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


class Fusion(StrEnum):
    RRF = "rrf"
    WEIGHTED = "weighted"


class SearchDocument(BaseModel):
    document_id: str
    # Chunks of one source share a parent_id; results are collapsed per parent.
    parent_id: str
    source_type: SourceType
    title: str
    text: str
    service: str | None = None
    environment: Environment | None = None
    severity: Severity | None = None
    timestamp: datetime | None = None
    incident_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None


class SearchFilters(BaseModel):
    service: str | None = None
    environment: Environment | None = None
    source_types: list[SourceType] | None = None
    exclude_incident_ids: list[str] = Field(default_factory=list)

    def matches(self, doc: SearchDocument) -> bool:
        # Documents without a service or environment (runbooks) apply to every service.
        if self.service and doc.service not in (None, self.service):
            return False
        if self.environment and doc.environment not in (None, self.environment):
            return False
        if self.source_types and doc.source_type not in self.source_types:
            return False
        return not (doc.incident_id and doc.incident_id in self.exclude_incident_ids)

    def to_es(self) -> dict[str, Any]:
        must: list[dict[str, Any]] = []
        for field, value in (("service", self.service), ("environment", self.environment)):
            if value:
                must.append(
                    {
                        "bool": {
                            "should": [
                                {"term": {field: str(value)}},
                                {"bool": {"must_not": {"exists": {"field": field}}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                )
        if self.source_types:
            must.append({"terms": {"source_type": [str(s) for s in self.source_types]}})
        must_not = (
            [{"terms": {"incident_id": self.exclude_incident_ids}}]
            if self.exclude_incident_ids
            else []
        )
        return {"bool": {"filter": must, "must_not": must_not}}


@dataclass(frozen=True)
class ScoredDocument:
    document: SearchDocument
    score: float


class SearchHit(BaseModel):
    document_id: str
    parent_id: str
    source_type: SourceType
    title: str
    excerpt: str
    score: float
    service: str | None
    incident_id: str | None
    metadata: dict[str, Any]
    bm25_rank: int | None = None
    vector_rank: int | None = None
