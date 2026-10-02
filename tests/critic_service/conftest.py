import httpx
import pytest
from starlette.applications import Starlette

from critic_service.client import A2ACriticClient
from critic_service.server import CriticSettings, create_app
from tests.agent.conftest import demo_state, registry  # noqa: F401
from tools.tool_registry import ToolRegistry

URL = "http://critic.test"


def asgi_http(app: Starlette) -> httpx.AsyncClient:
    """An HTTP client wired straight to the in-memory critic service."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL)


@pytest.fixture
def app(registry: ToolRegistry) -> Starlette:  # noqa: F811
    settings = CriticSettings(critic_public_url=URL, _env_file=None)  # type: ignore[call-arg]
    return create_app(settings, registry=registry, llm=None)


@pytest.fixture
def critic(app: Starlette) -> A2ACriticClient:
    return A2ACriticClient(URL, http_factory=lambda: asgi_http(app))
