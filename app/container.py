from dataclasses import dataclass

import structlog
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agents.llm import AnthropicLLM, StructuredLLM
from app.config import Settings
from auth.api_keys import ApiKeyAuthenticator, parse_key_config
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import SearchUnavailableError
from data.loader import load_incidents
from evals.service import EvaluationService
from graph.checkpoint import open_checkpointer
from graph.runner import IncidentAnalyzer
from graph.state import AgentDeps
from retrieval.backend import SearchBackend
from retrieval.factory import create_search_backend, embedder_from_settings, reranker_from_settings
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import build_documents, ingest
from storage.approvals import ApprovalStore
from storage.db import Database
from storage.incidents import IncidentRepository
from storage.runs import RunRepository
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
    analyzer: IncidentAnalyzer
    checkpointer: AsyncSqliteSaver
    evals: EvaluationService

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

        approvals = ApprovalStore(db)
        tools = build_default_registry(
            backend,
            TicketStore(),
            searcher,
            approvals=approvals,
            timeout_s=settings.tool_timeout_seconds,
        )
        deps = AgentDeps(
            tools=tools,
            llm=create_llm(settings),
            principal=AGENT_PRINCIPAL,
            max_retries=settings.max_critic_retries,
        )
        checkpointer = await open_checkpointer(settings.database_path)
        return cls(
            settings=settings,
            db=db,
            incidents=incidents,
            backend=backend,
            search_backend=search_backend,
            searcher=searcher,
            tools=tools,
            api_keys=ApiKeyAuthenticator(parse_key_config(settings.api_keys)),
            analyzer=IncidentAnalyzer(deps, RunRepository(db), approvals, checkpointer),
            checkpointer=checkpointer,
            evals=EvaluationService(settings, settings.eval_reports_dir),
        )

    async def close(self) -> None:
        await self.evals.shutdown()
        await self.analyzer.shutdown()
        await self.search_backend.close()
        await self.checkpointer.conn.close()
        await self.db.close()


def create_llm(settings: Settings) -> StructuredLLM | None:
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if settings.llm_provider == "heuristic" or (settings.llm_provider == "auto" and not key):
        log.info("llm_disabled", reason="heuristic mode")
        return None
    # With llm_provider=anthropic and no key, the SDK resolves credentials itself
    # (for example an `ant auth login` profile).
    return AnthropicLLM(settings.llm_model, api_key=key, timeout_s=settings.llm_timeout_seconds)


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
