from typing import Any

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_data_parts, new_data_message
from a2a.types import Role, SendMessageRequest, Task, TaskState
from starlette.applications import Starlette

from agents.critic_agent import review_plan
from agents.schemas import CriticVerdict
from critic_service.contract import RESULT_ARTIFACT, SKILL_ID, ReviewRequest, ReviewResult
from critic_service.server import CriticSettings, create_app
from tests.agent.conftest import demo_state, registry  # noqa: F401
from tools.tool_registry import ToolRegistry

URL = "http://critic.test"


@pytest.fixture
def app(registry: ToolRegistry) -> Starlette:  # noqa: F811
    settings = CriticSettings(critic_public_url=URL, _env_file=None)  # type: ignore[call-arg]
    return create_app(settings, registry=registry, llm=None)


def review_request(state: dict[str, Any], **changes: Any) -> ReviewRequest:
    state = {**state, **changes}
    return ReviewRequest(
        incident_id=state["incident"].incident_id,
        service=state["incident"].service,
        remediation_plan=state["remediation_plan"],
        selected_root_cause=state["selected_root_cause"],
        root_cause_confidence=state["root_cause_confidence"],
        hypotheses=state["root_cause_hypotheses"],
        evidence=state["evidence"],
    )


async def send(app: Starlette, payload: dict[str, Any]) -> Task:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL) as http:
        card = await A2ACardResolver(http, URL).get_agent_card()
        client = await create_client(card, ClientConfig(streaming=False, httpx_client=http))
        message = new_data_message(payload, media_type="application/json", role=Role.ROLE_USER)
        chunks = [chunk async for chunk in client.send_message(SendMessageRequest(message=message))]
    assert len(chunks) == 1
    assert chunks[0].HasField("task")
    return chunks[0].task


def result_of(task: Task) -> ReviewResult:
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    (artifact,) = task.artifacts
    assert artifact.name == RESULT_ARTIFACT
    (data,) = get_data_parts(artifact.parts)
    return ReviewResult.model_validate(data)


async def test_agent_card_advertises_one_skill(app: Starlette) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL) as http:
        card = await A2ACardResolver(http, URL).get_agent_card()
    assert [s.id for s in card.skills] == [SKILL_ID]
    (interface,) = card.supported_interfaces
    assert (interface.protocol_binding, interface.url, interface.protocol_version) == (
        "JSONRPC",
        URL,
        "1.0",
    )


async def test_approved_verdict(app: Starlette, demo_state: dict[str, Any]) -> None:  # noqa: F811
    request = review_request(demo_state)
    result = result_of(await send(app, request.model_dump(mode="json")))
    assert result.approved is True
    assert result.verdict is CriticVerdict.APPROVE
    assert result.risk_level is request.remediation_plan.overall_risk
    assert result.agent_call.agent == "critic"
    assert result.agent_call.mode == "heuristic"


async def test_rejected_verdict(app: Starlette, demo_state: dict[str, Any]) -> None:  # noqa: F811
    request = review_request(demo_state, root_cause_confidence=0.1)
    result = result_of(await send(app, request.model_dump(mode="json")))
    assert result.approved is False
    assert result.verdict is CriticVerdict.NEED_MORE_EVIDENCE
    assert any("confidence" in reason for reason in result.reasons)


async def test_verdict_matches_in_process_critic(
    app: Starlette,
    demo_state: dict[str, Any],  # noqa: F811
    registry: ToolRegistry,  # noqa: F811
) -> None:
    selected = demo_state["selected_root_cause"]
    contradicted = selected.model_copy(
        update={"evidence_for": ["E1"], "evidence_against": ["E2", "E3"]}
    )
    request = review_request(demo_state, selected_root_cause=contradicted)
    local, _ = await review_plan(request.as_state(), registry, None)  # type: ignore[arg-type]
    remote = result_of(await send(app, request.model_dump(mode="json")))
    assert remote.as_review() == local


async def test_malformed_request_is_rejected(app: Starlette) -> None:
    task = await send(app, {"incident_id": "INC-1060"})
    assert task.status.state == TaskState.TASK_STATE_REJECTED
    assert not task.artifacts


async def test_health(app: Starlette) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL) as http:
        response = await http.get("/health")
    assert response.json()["status"] == "ok"
