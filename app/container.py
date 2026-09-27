from dataclasses import dataclass

import structlog

from app.config import Settings
from auth.api_keys import ApiKeyAuthenticator, parse_key_config
from core.exceptions import SearchUnavailableError
from data.loader import load_incidents
from retrieval.backend import SearchBackend
from retrieval.factory import create_search_backend, embedder_from_settings, reranker_from_settings
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import build_documents, ingest
from storage.db import Database
from storage.incidents import IncidentRepository
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import ToolRegistry, build_default_registry

log = structlog.get_logger(__name__)


@dataclass
class Container:
    """Long-lived application services, built once at startup."""

    settings: Settings
    db: Database
    incidents: IncidentRepository
    backend: SimulatedOpsBackend
    search_backend: SearchBackend
    searcher: HybridSearcher
    tools: ToolRegistry
    api_keys: ApiKeyAuthenticator

    @classmethod
    async def create(cls, settings: Settings) -> "Container":
        db = Database(settings.database_path)
        await db.connect()
        incidents = IncidentRepository(db)
        if settings.seed_incidents and await incidents.count() == 0:
            await incidents.seed(load_incidents(settings.data_dir))

        backend = SimulatedOpsBackend.from_data_dir(settings.data_dir)
        search_backend = create_search_backend(settings)
        embedder = embedder_from_settings(settings)
        searcher = HybridSearcher(search_backend, embedder, reranker_from_settings(settings))
        if settings.auto_index:
            await _ensure_indexed(settings, search_backend, searcher, backend)

        tools = build_default_registry(
            backend, TicketStore(), searcher, timeout_s=settings.tool_timeout_seconds
        )
        return cls(
            settings=settings,
            db=db,
            incidents=incidents,
            backend=backend,
            search_backend=search_backend,
            searcher=searcher,
            tools=tools,
            api_keys=ApiKeyAuthenticator(parse_key_config(settings.api_keys)),
        )

    async def close(self) -> None:
        await self.search_backend.close()
        await self.db.close()


async def _ensure_indexed(
    settings: Settings,
    search_backend: SearchBackend,
    searcher: HybridSearcher,
    ops: SimulatedOpsBackend,
) -> None:
    # The API still starts when Elasticsearch is down; /health reports it and search
    # calls fail with SearchUnavailableError until it is reachable.
    try:
        if await search_backend.count() == 0:
            docs = build_documents(settings.data_dir, ops)
            await ingest(search_backend, searcher.embedder, docs)
    except SearchUnavailableError as exc:
        log.error("search_index_unavailable", error=exc.message)
