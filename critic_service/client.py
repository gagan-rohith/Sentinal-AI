"""The orchestrator's side of the A2A hop: a client for the critic service and the graph node
that uses it in place of the in-process critic (CRITIC_MODE=a2a)."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import structlog
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, new_data_message
from a2a.types import AgentCard, Role, SendMessageRequest, Task, TaskState

from agents.critic_agent import apply_review, unavailable_update
from core.exceptions import CriticUnavailableError
from critic_service.contract import (
    MEDIA_TYPE,
    RESULT_ARTIFACT,
    SKILL_ID,
    ReviewRequest,
    ReviewResult,
)
from graph.state import AgentDeps, IncidentState
from observability.metrics import record_agent_call

log = structlog.get_logger(__name__)

HttpFactory = Callable[[], httpx.AsyncClient]


def result_from_task(task: Task | None) -> ReviewResult:
    if task is None:
        raise CriticUnavailableError("critic service returned no task")
    if task.status.state != TaskState.TASK_STATE_COMPLETED:
        state = TaskState.Name(task.status.state)
        detail = get_message_text(task.status.message) if task.status.HasField("message") else ""
        raise CriticUnavailableError(f"critic task ended as {state}: {detail}".rstrip(": "))
    for artifact in task.artifacts:
        if artifact.name == RESULT_ARTIFACT:
            data = get_data_parts(artifact.parts)
            if data:
                return ReviewResult.model_validate(data[0])
    raise CriticUnavailableError(f"critic task completed without a {RESULT_ARTIFACT} artifact")


class A2ACriticClient:
    """Delegates review_remediation_plan to the critic service over A2A (JSON-RPC)."""

    def __init__(
        self, url: str, *, timeout_s: float = 10.0, http_factory: HttpFactory | None = None
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=timeout_s))
        self._card: AgentCard | None = None

    async def review(self, request: ReviewRequest) -> ReviewResult:
        """Any failure, including a timeout, becomes CriticUnavailableError."""
        try:
            return await asyncio.wait_for(self._review(request), self.timeout_s)
        except CriticUnavailableError:
            raise
        except TimeoutError:
            raise CriticUnavailableError(
                f"critic service did not answer within {self.timeout_s}s"
            ) from None
        except Exception as exc:
            raise CriticUnavailableError(
                f"critic service call failed: {type(exc).__name__}: {exc}"
            ) from exc

    async def _review(self, request: ReviewRequest) -> ReviewResult:
        http = self._http_factory()
        client: Any = None
        try:
            card = self._card or await self._resolve_card(http)
            client = await create_client(card, ClientConfig(streaming=False, httpx_client=http))
            message = new_data_message(
                request.model_dump(mode="json"), media_type=MEDIA_TYPE, role=Role.ROLE_USER
            )
            task: Task | None = None
            async for chunk in client.send_message(SendMessageRequest(message=message)):
                if chunk.HasField("task"):
                    task = chunk.task
            return result_from_task(task)
        finally:
            # Closing the A2A client closes the HTTP client it was given.
            await (client.close() if client is not None else http.aclose())

    async def _resolve_card(self, http: httpx.AsyncClient) -> AgentCard:
        card = await A2ACardResolver(http, self.url).get_agent_card()
        if not any(skill.id == SKILL_ID for skill in card.skills):
            raise CriticUnavailableError(f"agent at {self.url} does not offer the {SKILL_ID} skill")
        self._card = card
        return card


async def remote_critic_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    if deps.critic is None:
        raise RuntimeError("remote_critic_node needs AgentDeps.critic")
    try:
        result = await deps.critic.review(ReviewRequest.from_state(state))
    except CriticUnavailableError as exc:
        log.warning("critic_unavailable", error=exc.message)
        return unavailable_update(exc.message)
    # The service records the call in its own metrics; record it here too, so the
    # orchestrator's /metrics still covers every agent step of its runs.
    record_agent_call(result.agent_call)
    log.info("critic_review_received", verdict=result.verdict.value, via="a2a")
    return apply_review(deps, state, result.as_review(), result.agent_call)
