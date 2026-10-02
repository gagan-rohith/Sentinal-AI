from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from auth.permissions import AGENT_PRINCIPAL
from critic_service.client import A2ACriticClient, remote_critic_node
from graph.state import AgentDeps
from observability.otel import configure_tracing, otel_trace_id
from tools.tool_registry import ToolRegistry

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracing() -> None:
    # The global tracer provider can be set once per process; this module owns it.
    configure_tracing("sentinel-test", env={}, processor=SimpleSpanProcessor(EXPORTER))


@pytest.fixture
def spans() -> Iterator[list[ReadableSpan]]:
    EXPORTER.clear()
    collected: list[ReadableSpan] = []
    yield collected
    EXPORTER.clear()


def named(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    return next(s for s in spans if s.name == name)


async def test_one_trace_spans_the_orchestrator_and_the_critic(
    registry: ToolRegistry,
    critic: A2ACriticClient,
    demo_state: dict[str, Any],
    spans: list[ReadableSpan],
) -> None:
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL, critic=critic)
    await remote_critic_node(deps, {**demo_state, "trace_id": TRACE_ID})  # type: ignore[arg-type]
    spans.extend(EXPORTER.get_finished_spans())

    client = named(spans, "critic.review_remediation_plan")
    server = named(spans, "POST /")
    review = named(spans, "critic.review_plan")

    # Every span, on both sides of the hop, is in the run's trace.
    assert {s.context.trace_id for s in spans} == {int(TRACE_ID, 16)}
    assert client.kind is SpanKind.CLIENT
    assert client.parent is None
    assert server.kind is SpanKind.SERVER

    # The server span continues the trace from the traceparent the client sent...
    by_id = {s.context.span_id: s for s in spans}
    assert server.parent is not None
    assert server.parent.is_remote
    assert by_id[server.parent.span_id].kind is SpanKind.CLIENT
    # ...so the review inside the critic service chains up to the orchestrator's span.
    chain, current = [], review
    while current.parent is not None:
        current = by_id[current.parent.span_id]
        chain.append(current.name)
    assert chain[-1] == "critic.review_remediation_plan"
    assert "POST /" in chain
    assert review.attributes is not None
    assert review.attributes["sentinel.critic.verdict"] == "approve"
    assert client.attributes is not None
    assert client.attributes["sentinel.critic.verdict"] == "approve"


async def test_unavailable_critic_marks_the_span_as_an_error(
    registry: ToolRegistry, demo_state: dict[str, Any], spans: list[ReadableSpan]
) -> None:
    down = A2ACriticClient("http://127.0.0.1:9", timeout_s=2)
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL, critic=down)
    await remote_critic_node(deps, {**demo_state, "trace_id": TRACE_ID})  # type: ignore[arg-type]
    spans.extend(EXPORTER.get_finished_spans())

    client = named(spans, "critic.review_remediation_plan")
    assert client.status.status_code is StatusCode.ERROR
    assert client.context.trace_id == int(TRACE_ID, 16)


def test_tracing_is_off_without_configuration() -> None:
    assert configure_tracing("sentinel-test", env={}) is False


def test_trace_ids_map_to_valid_otel_ids() -> None:
    assert otel_trace_id(TRACE_ID) == int(TRACE_ID, 16)
    custom = otel_trace_id("caller-supplied-id")
    assert custom == otel_trace_id("caller-supplied-id")
    assert 0 < custom < 2**128
