import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

from agents.schemas import ApprovalRequest, ProposedAction, Risk
from auth.api_keys import ApiKeyAuthenticator, hash_key
from auth.permissions import Principal
from core.enums import Role
from core.models import Incident
from mcp_server.auth import ENV_API_KEY, extract_key, resolve_principal
from mcp_server.server import build_server
from retrieval.hybrid_search import HybridSearcher
from storage.approvals import ApprovalStore
from storage.db import Database
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import ToolRegistry, build_default_registry

KEYS = {Role.VIEWER: "mcp-viewer", Role.OPERATOR: "mcp-operator", Role.ADMIN: "mcp-admin"}
AUTH = ApiKeyAuthenticator({hash_key(k): role for role, k in KEYS.items()})
EXPECTED_TOOLS = {
    "search_logs",
    "get_metrics",
    "get_service_health",
    "search_runbooks",
    "search_incidents",
    "get_deployment_status",
    "create_ticket",
    "restart_service",
    "rollback_deployment",
}


@pytest.fixture
async def approvals() -> AsyncIterator[ApprovalStore]:
    db = Database(":memory:")
    await db.connect()
    yield ApprovalStore(db)
    await db.close()


@pytest.fixture
def registry(
    backend: SimulatedOpsBackend, searcher: HybridSearcher, approvals: ApprovalStore
) -> ToolRegistry:
    return build_default_registry(backend, TicketStore(), searcher, approvals=approvals)


async def call(
    registry: ToolRegistry, tool: str, args: dict[str, Any], key: str | None
) -> CallToolResult:
    env = {ENV_API_KEY: key} if key else {}
    async with Client(build_server(registry, AUTH, env=env)) as client:
        return await client.call_tool(tool, args)


def error_of(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error
    text = result.content[0].text  # type: ignore[union-attr]
    payload: dict[str, Any] = json.loads(text[text.index("{") :])["error"]
    return payload


async def test_exposes_the_nine_tools_with_schemas(registry: ToolRegistry) -> None:
    async with Client(build_server(registry, AUTH, env={})) as client:
        listed = (await client.list_tools()).tools
    by_name = {t.name: t for t in listed}
    assert set(by_name) == EXPECTED_TOOLS
    assert all(t.description and t.output_schema for t in listed)

    destructive = {t.name for t in listed if t.annotations and t.annotations.destructive_hint}
    assert destructive == {"restart_service", "rollback_deployment"}
    assert set(by_name["restart_service"].input_schema["required"]) == {"service", "approval_id"}
    assert set(by_name["rollback_deployment"].input_schema["required"]) == {
        "service",
        "deployment_id",
        "approval_id",
    }
    read_only = {t.name for t in listed if t.annotations and t.annotations.read_only_hint}
    assert read_only == EXPECTED_TOOLS - {"create_ticket", "restart_service", "rollback_deployment"}


async def test_operator_gets_structured_logs(
    registry: ToolRegistry, demo_incident: Incident
) -> None:
    result = await call(
        registry,
        "search_logs",
        {"service": "checkout-api", "end_time": demo_incident.timestamp.isoformat()},
        KEYS[Role.OPERATOR],
    )
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["error_count"] > 0
    assert any("Connection is not available" in p["example"]
               for p in result.structured_content["top_errors"])  # fmt: skip


async def test_search_tools(registry: ToolRegistry) -> None:
    runbooks = await call(
        registry, "search_runbooks", {"query": "connection pool exhausted"}, KEYS[Role.OPERATOR]
    )
    assert runbooks.structured_content is not None
    assert runbooks.structured_content["hits"][0]["source_type"] == "runbook"

    incidents = await call(
        registry,
        "search_incidents",
        {"query": "5xx after traffic increase", "exclude_incident_ids": ["INC-1001"]},
        KEYS[Role.OPERATOR],
    )
    assert incidents.structured_content is not None
    ids = {h["incident_id"] for h in incidents.structured_content["hits"]}
    assert ids
    assert "INC-1001" not in ids


async def test_ticket_creation_needs_operator(registry: ToolRegistry) -> None:
    args = {
        "title": "Pool exhaustion follow-up",
        "service": "checkout-api",
        "severity": "sev2",
        "description": "Add PgBouncer in front of the checkout database.",
        "incident_id": "INC-1060",
    }
    created = await call(registry, "create_ticket", args, KEYS[Role.OPERATOR])
    assert created.structured_content is not None
    assert created.structured_content["ticket_id"].startswith("OPS-")
    assert error_of(await call(registry, "create_ticket", args, KEYS[Role.VIEWER]))["code"] == (
        "forbidden"
    )


@pytest.mark.parametrize(("key", "message"), [(None, "no API key"), ("wrong", "invalid API key")])
async def test_unauthenticated_calls_are_refused(
    registry: ToolRegistry, key: str | None, message: str
) -> None:
    error = error_of(await call(registry, "get_metrics", {"service": "checkout-api"}, key))
    assert error["code"] == "unauthenticated"
    assert message in error["message"]


async def test_viewer_cannot_read_tools(registry: ToolRegistry) -> None:
    error = error_of(
        await call(registry, "get_service_health", {"service": "checkout-api"}, KEYS[Role.VIEWER])
    )
    assert error["code"] == "forbidden"


async def test_errors_are_structured(registry: ToolRegistry) -> None:
    missing = error_of(
        await call(registry, "get_metrics", {"service": "nope-svc"}, KEYS[Role.OPERATOR])
    )
    assert missing["code"] == "not_found"

    invalid = await call(
        registry, "search_logs", {"service": "checkout-api", "minutes": 0}, KEYS[Role.OPERATOR]
    )
    assert invalid.is_error


async def test_destructive_tools_need_admin(registry: ToolRegistry) -> None:
    args = {"service": "checkout-api", "approval_id": "apr-000000000000"}
    error = error_of(await call(registry, "restart_service", args, KEYS[Role.OPERATOR]))
    assert error["code"] == "forbidden"


async def test_destructive_tools_need_an_approval(registry: ToolRegistry) -> None:
    args = {
        "service": "checkout-api",
        "deployment_id": "dep-00157",
        "approval_id": "apr-000000000000",
    }
    error = error_of(await call(registry, "rollback_deployment", args, KEYS[Role.ADMIN]))
    assert error["code"] == "approval_required"


async def test_approved_action_runs_once(registry: ToolRegistry, approvals: ApprovalStore) -> None:
    request = ApprovalRequest(
        run_id="run-0123456789ab",
        incident_id="INC-1060",
        service="checkout-api",
        root_cause="PostgreSQL connection pool exhaustion",
        root_cause_confidence=0.7,
        actions=[
            ProposedAction(
                tool="restart_service",
                arguments={"service": "checkout-api"},
                description="Rolling restart to release leaked connections",
                risk=Risk.MEDIUM,
            )
        ],
        overall_risk=Risk.MEDIUM,
        rollback_plan="none needed",
        unresolved_critic_issues=[],
    )
    record = await approvals.create(request)
    admin = Principal(subject="alice", role=Role.ADMIN, auth_method="test")
    await approvals.decide(request.run_id, approved=True, principal=admin, comment=None)

    args = {"service": "checkout-api", "approval_id": record.approval_id}
    first = await call(registry, "restart_service", args, KEYS[Role.ADMIN])
    assert not first.is_error
    assert first.structured_content is not None
    assert first.structured_content["action"] == "restart_service"
    assert first.structured_content["simulated"] is True

    replay = error_of(await call(registry, "restart_service", args, KEYS[Role.ADMIN]))
    assert replay["code"] == "approval_required"

    other_service = {"service": "search-api", "approval_id": record.approval_id}
    mismatch = error_of(await call(registry, "restart_service", other_service, KEYS[Role.ADMIN]))
    assert mismatch["code"] == "approval_required"
    assert datetime.now(UTC) >= (await approvals.get(record.approval_id)).requested_at


@pytest.mark.parametrize(
    ("headers", "env", "expected"),
    [
        (None, {ENV_API_KEY: "from-env"}, "from-env"),
        (None, {}, None),
        ({"X-API-Key": "k1"}, {ENV_API_KEY: "ignored"}, "k1"),
        ({"authorization": "Bearer k2"}, {}, "k2"),
        ({"Authorization": "Basic abc"}, {}, None),
        ({}, {ENV_API_KEY: "ignored-over-http"}, None),
    ],
)
def test_key_extraction(
    headers: dict[str, str] | None, env: dict[str, str], expected: str | None
) -> None:
    assert extract_key(headers, env) == expected


def test_http_principal_is_marked_as_mcp() -> None:
    principal = resolve_principal(AUTH, {"X-API-Key": KEYS[Role.ADMIN]}, {})
    assert principal.role is Role.ADMIN
    assert principal.auth_method == "mcp:api_key"
