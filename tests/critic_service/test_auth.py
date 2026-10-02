from typing import Any

import pytest
from a2a.client import A2ACardResolver
from starlette.applications import Starlette

from agents.critic_agent import unavailable_update
from app.config import Settings
from app.container import _remote_critic
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import CriticUnavailableError
from critic_service.auth import parse_key_hashes
from critic_service.client import A2ACriticClient, remote_critic_node
from critic_service.contract import ReviewRequest
from critic_service.server import create_app
from graph.state import AgentDeps
from tests.critic_service.conftest import URL, asgi_http, critic_settings
from tools.tool_registry import ToolRegistry


async def test_agent_card_is_public_and_declares_the_api_key(app: Starlette) -> None:
    async with asgi_http(app, key=None) as http:
        card = await A2ACardResolver(http, URL).get_agent_card()
    scheme = card.security_schemes["apiKey"].api_key_security_scheme
    assert (scheme.location, scheme.name) == ("header", "X-API-Key")
    assert [list(r.schemes) for r in card.security_requirements] == [["apiKey"]]


async def test_health_is_public(app: Starlette) -> None:
    async with asgi_http(app, key=None) as http:
        assert (await http.get("/health")).status_code == 200


async def test_request_without_key_is_rejected(app: Starlette) -> None:
    async with asgi_http(app, key=None) as http:
        response = await http.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_bad_api_key_is_rejected(app: Starlette, demo_state: dict[str, Any]) -> None:
    client = A2ACriticClient(
        URL, api_key="sk_sentinel_wrong-key", http_factory=lambda: asgi_http(app, key=None)
    )
    with pytest.raises(CriticUnavailableError, match="401"):
        await client.review(ReviewRequest.from_state(demo_state))


async def test_bad_api_key_sends_the_run_to_human_review(
    app: Starlette, registry: ToolRegistry, demo_state: dict[str, Any]
) -> None:
    client = A2ACriticClient(
        URL, api_key="sk_sentinel_wrong-key", http_factory=lambda: asgi_http(app, key=None)
    )
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL, critic=client)
    update = await remote_critic_node(deps, demo_state)  # type: ignore[arg-type]
    assert update.keys() == unavailable_update("x").keys()
    assert update["approval_required"] is True
    assert "401" in update["critic_feedback"].issues[0]


def test_service_refuses_to_start_without_keys(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError, match="refuses to run without authentication"):
        create_app(critic_settings(critic_api_key_sha256=""), registry=registry, llm=None)


def test_pasted_key_is_rejected_without_echoing_it() -> None:
    secret = "sk_sentinel_this-is-a-secret"
    with pytest.raises(ValueError, match="entry 1 is not a SHA-256") as error:
        parse_key_hashes(secret)
    assert secret not in str(error.value)


def test_a2a_mode_needs_a_client_key() -> None:
    settings = Settings(critic_mode="a2a", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="CRITIC_API_KEY"):
        _remote_critic(settings)
