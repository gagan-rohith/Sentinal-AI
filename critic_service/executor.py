from typing import cast

import structlog
from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from opentelemetry import trace
from pydantic import ValidationError

from agents.critic_agent import review_plan
from agents.llm import StructuredLLM
from critic_service.contract import MEDIA_TYPE, RESULT_ARTIFACT, ReviewRequest, ReviewResult
from graph.state import IncidentState
from tools.tool_registry import ToolRegistry

log = structlog.get_logger(__name__)


def parse_request(parts: list[dict[str, object]]) -> ReviewRequest:
    if not parts:
        raise ValueError("expected one JSON data part with the review request")
    return ReviewRequest.model_validate(parts[0])


class CriticAgentExecutor(AgentExecutor):
    """Runs the existing critic (agents.critic_agent.review_plan) for one A2A task."""

    def __init__(self, registry: ToolRegistry, llm: StructuredLLM | None) -> None:
        # The registry is only used for its tool input schemas; the critic never invokes tools.
        self.registry = registry
        self.llm = llm

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ValueError("request has no message")
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)

        try:
            request = parse_request(get_data_parts(context.message.parts))
        except (ValueError, ValidationError) as exc:
            log.warning("critic_request_rejected", error=str(exc)[:300])
            await updater.reject(new_text_message(f"invalid review request: {exc}"))
            return

        await updater.start_work()
        tracer = trace.get_tracer(__name__)
        try:
            with tracer.start_as_current_span(
                "critic.review_plan", attributes={"sentinel.incident_id": request.incident_id}
            ) as span:
                state = cast(IncidentState, request.as_state())
                review, call = await review_plan(state, self.registry, self.llm)
                span.set_attribute("sentinel.critic.verdict", review.verdict.value)
                span.set_attribute("sentinel.critic.mode", call.mode)
        except Exception as exc:
            log.exception("critic_review_failed", incident_id=request.incident_id)
            await updater.failed(new_text_message(f"review failed: {type(exc).__name__}: {exc}"))
            return

        result = ReviewResult.from_review(review, call, request.remediation_plan)
        await updater.add_artifact(
            parts=[new_data_part(result.model_dump(mode="json"), media_type=MEDIA_TYPE)],
            name=RESULT_ARTIFACT,
        )
        await updater.complete()
        log.info(
            "critic_review_completed",
            incident_id=request.incident_id,
            verdict=result.verdict.value,
            mode=call.mode,
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # A review takes milliseconds to seconds; there is nothing useful to cancel.
        raise NotImplementedError("cancel is not supported")
