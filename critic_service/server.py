"""The critic as a standalone A2A service.

Run with: python -m critic_service
The Agent Card is served at /.well-known/agent-card.json and JSON-RPC at /.
"""

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from pydantic_settings import SettingsConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agents.llm import StructuredLLM
from app.config import Settings
from app.container import create_llm
from critic_service.contract import MEDIA_TYPE, SKILL_ID
from critic_service.executor import CriticAgentExecutor
from retrieval.backend import InMemoryBackend
from retrieval.embeddings import HashEmbedder
from retrieval.hybrid_search import HybridSearcher
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import ToolRegistry, build_default_registry

VERSION = "0.1.0"


class CriticSettings(Settings):
    """The API's settings (LLM, data directory, logging) plus where the service listens."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    critic_host: str = "0.0.0.0"
    critic_port: int = 8100
    # The URL clients reach the service on, advertised in the Agent Card.
    critic_public_url: str = "http://localhost:8100"


def build_agent_card(public_url: str) -> AgentCard:
    skill = AgentSkill(
        id=SKILL_ID,
        name="Review remediation plan",
        description=(
            "Checks an incident remediation plan against the evidence it cites: evidence ids "
            "exist, the root cause is supported, actions have valid arguments. Returns a "
            "structured verdict."
        ),
        input_modes=[MEDIA_TYPE],
        output_modes=[MEDIA_TYPE],
        tags=["sre", "incident-response", "critic"],
    )
    return AgentCard(
        name="SentinelAI Critic",
        description="Reviews incident remediation plans for SentinelAI.",
        version=VERSION,
        default_input_modes=[MEDIA_TYPE],
        default_output_modes=[MEDIA_TYPE],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=public_url, protocol_version="1.0")
        ],
        skills=[skill],
    )


def validation_registry(settings: Settings) -> ToolRegistry:
    """The tool registry the critic validates proposed actions against.

    Only tool input schemas are used, so search runs on an empty in-memory backend.
    """
    searcher = HybridSearcher(InMemoryBackend(), HashEmbedder())
    return build_default_registry(
        SimulatedOpsBackend.from_data_dir(settings.data_dir), TicketStore(), searcher
    )


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": VERSION})


def create_app(
    settings: CriticSettings | None = None,
    *,
    registry: ToolRegistry | None = None,
    llm: StructuredLLM | None = None,
) -> Starlette:
    settings = settings or CriticSettings()
    card = build_agent_card(settings.critic_public_url)
    executor = CriticAgentExecutor(
        registry or validation_registry(settings),
        llm if llm is not None else create_llm(settings),
    )
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card
    )
    routes = [Route("/health", health, methods=["GET"])]
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)
