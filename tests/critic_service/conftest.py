import httpx
import pytest
from starlette.applications import Starlette

from auth.api_keys import hash_key
from critic_service.client import A2ACriticClient
from critic_service.server import CriticSettings, create_app
from tests.agent.conftest import demo_state, registry  # noqa: F401
from tools.tool_registry import ToolRegistry

URL = "http://critic.test"
KEY = "sk_sentinel_test-critic-key"


def asgi_http(app: Starlette, key: str | None = KEY) -> httpx.AsyncClient:
    """An HTTP client wired straight to the in-memory critic service."""
    headers = {"X-API-Key": key} if key else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL, headers=headers)


def critic_settings(**overrides: object) -> CriticSettings:
    values: dict[str, object] = {
        "critic_public_url": URL,
        "critic_api_key_sha256": hash_key(KEY),
        "_env_file": None,
    }
    values.update(overrides)
    return CriticSettings(**values)  # type: ignore[arg-type]


@pytest.fixture
def app(registry: ToolRegistry) -> Starlette:  # noqa: F811
    return create_app(critic_settings(), registry=registry, llm=None)


@pytest.fixture
def critic(app: Starlette) -> A2ACriticClient:
    # No default headers: the key must come from the SDK's auth interceptor.
    return A2ACriticClient(URL, api_key=KEY, http_factory=lambda: asgi_http(app, key=None))
