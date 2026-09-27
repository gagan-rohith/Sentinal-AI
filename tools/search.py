from pydantic import BaseModel, Field

from core.enums import Environment, SourceType
from core.models import ServiceName
from retrieval.hybrid_search import HybridSearcher
from retrieval.models import Fusion, SearchHit, SearchMode


class SearchQuery(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    exclude_incident_ids: list[str] = Field(
        default_factory=list, description="Incidents to leave out, such as the one being analysed"
    )


class KnowledgeQuery(SearchQuery):
    service: ServiceName | None = None
    environment: Environment | None = None
    source_types: list[SourceType] | None = None
    mode: SearchMode = SearchMode.HYBRID
    fusion: Fusion = Fusion.RRF


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


async def search_knowledge(searcher: HybridSearcher, query: KnowledgeQuery) -> SearchResults:
    hits = await searcher.search(
        query.query,
        service=query.service,
        environment=query.environment,
        source_types=query.source_types,
        exclude_incident_ids=query.exclude_incident_ids,
        top_k=query.top_k,
        mode=query.mode,
        fusion=query.fusion,
    )
    return SearchResults(query=query.query, hits=hits)


# Runbooks and past incidents are searched across all services: the same failure mode
# on another service is still useful evidence.


async def search_runbooks(searcher: HybridSearcher, query: SearchQuery) -> SearchResults:
    return await search_knowledge(
        searcher, KnowledgeQuery(**query.model_dump(), source_types=[SourceType.RUNBOOK])
    )


async def search_similar_incidents(searcher: HybridSearcher, query: SearchQuery) -> SearchResults:
    return await search_knowledge(
        searcher, KnowledgeQuery(**query.model_dump(), source_types=[SourceType.INCIDENT])
    )
