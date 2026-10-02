import asyncio
from typing import Any

import httpx
import pytest
from a2a.helpers import new_task, new_text_message
from a2a.types import TaskState

from agents.schemas import CriticVerdict
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import CriticUnavailableError
from core.models import Incident
from critic_service.client import A2ACriticClient, remote_critic_node, result_from_task
from critic_service.contract import ReviewRequest, ReviewResult
from graph.state import AgentDeps, IncidentState
from tests.agent.conftest import run_graph
from tools.tool_registry import ToolRegistry

READ_ONLY_INCIDENT = "INC-1003"
CLOSED_PORT = "http://127.0.0.1:9"


class CountingCritic:
    """Passes reviews through to the real client and counts them."""

    def __init__(self, inner: A2ACriticClient) -> None:
        self.inner = inner
        self.results: list[ReviewResult] = []

    async def review(self, request: ReviewRequest) -> ReviewResult:
        result = await self.inner.review(request)
        self.results.append(result)
        return result


def deps_with(registry: ToolRegistry, critic: Any) -> AgentDeps:
    return AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL, critic=critic)


async def test_run_gets_approved_verdict_over_a2a(
    registry: ToolRegistry, critic: A2ACriticClient, demo_incident: Incident
) -> None:
    counting = CountingCritic(critic)
    state = await run_graph(deps_with(registry, counting), demo_incident)

    assert [r.verdict for r in counting.results] == [CriticVerdict.APPROVE]
    report = state["final_report"]
    assert report.critic_review.verdict is CriticVerdict.APPROVE
    assert report.selected_root_cause.title == "PostgreSQL connection pool exhaustion"
    assert [c.agent for c in report.agent_calls].count("critic") == 1


async def test_rejected_verdict_over_a2a_uses_the_retry_budget(
    registry: ToolRegistry, critic: A2ACriticClient, demo_state: dict[str, Any]
) -> None:
    state: IncidentState = {**demo_state, "root_cause_confidence": 0.1, "retry_count": 0}  # type: ignore[typeddict-item]
    update = await remote_critic_node(deps_with(registry, critic), state)

    assert update["critic_feedback"].verdict is CriticVerdict.NEED_MORE_EVIDENCE
    assert update["retry_count"] == 1
    assert "unresolved_critic_issues" not in update
    assert update["agent_calls"][0].agent == "critic"


async def test_service_down_sends_run_to_human_review(
    registry: ToolRegistry, incidents: list[Incident]
) -> None:
    incident = next(i for i in incidents if i.incident_id == READ_ONLY_INCIDENT)
    down = A2ACriticClient(CLOSED_PORT, timeout_s=2)
    state = await run_graph(deps_with(registry, down), incident, resume_with=None)

    # A plan with no production change still stops for a person when nobody reviewed it.
    assert state["__next__"] == ("human_approval",)
    assert state["remediation_plan"].approval_required is False
    assert state["unresolved_critic_issues"] is True
    assert state["retry_count"] == 0
    assert state["critic_feedback"].issues[0].startswith("critic unavailable:")
    assert any("critic review failed" in gap for gap in state["data_gaps"])


async def test_timeout_is_reported_as_unavailable(demo_state: dict[str, Any]) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    client = A2ACriticClient(
        "http://critic.test",
        timeout_s=0.2,
        http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow)),
    )
    with pytest.raises(CriticUnavailableError, match=r"did not answer within 0.2s"):
        await client.review(ReviewRequest.from_state(demo_state))


def test_failed_task_is_reported_with_its_message() -> None:
    task = new_task(task_id="t1", context_id="ctx", state=TaskState.TASK_STATE_FAILED)
    task.status.message.CopyFrom(new_text_message("review failed: boom"))
    with pytest.raises(CriticUnavailableError, match="TASK_STATE_FAILED: review failed: boom"):
        result_from_task(task)
