"""OpenTelemetry tracing across the orchestrator and the critic service.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set (spans then go to that OTLP/HTTP collector, for
example Jaeger) or OTEL_TRACES_EXPORTER=console (spans are printed). Like LangSmith, nothing
leaves the process without explicit configuration.

A run's OpenTelemetry trace id is its SentinelAI trace id, so the id in a report, in the
X-Trace-Id header and in the logs is the one to search for in the trace viewer. Trace context
crosses the A2A hop as a W3C traceparent header, which the a2a SDK does not send itself.
"""

import contextvars
import hashlib
import os
import re
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager

import httpx
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import SpanKind
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_run_trace_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "otel_run_trace_id", default=None
)


def otel_trace_id(trace_id: str) -> int:
    """SentinelAI trace id -> OpenTelemetry trace id. Non-hex ids are hashed to fit."""
    value = trace_id.lower()
    if _HEX32.fullmatch(value) and int(value, 16):
        return int(value, 16)
    return int(hashlib.sha256(trace_id.encode()).hexdigest()[:32], 16)


class RunIdGenerator(RandomIdGenerator):
    """Root spans started inside run_trace() take the run's trace id."""

    def generate_trace_id(self) -> int:
        return _run_trace_id.get() or super().generate_trace_id()


@contextmanager
def run_trace(trace_id: str | None) -> Iterator[None]:
    token = _run_trace_id.set(otel_trace_id(trace_id) if trace_id else None)
    try:
        yield
    finally:
        _run_trace_id.reset(token)


def configure_tracing(
    service_name: str,
    env: Mapping[str, str] | None = None,
    processor: SpanProcessor | None = None,
) -> bool:
    """Install a tracer provider if tracing is configured. Returns whether it is on."""
    env = os.environ if env is None else env
    endpoint = env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if processor is None:
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            processor = BatchSpanProcessor(OTLPSpanExporter())
        elif env.get("OTEL_TRACES_EXPORTER") == "console":
            processor = SimpleSpanProcessor(ConsoleSpanExporter())
        else:
            return False
    resource = Resource.create({"service.name": env.get("OTEL_SERVICE_NAME", service_name)})
    provider = TracerProvider(resource=resource, id_generator=RunIdGenerator())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return True


async def inject_trace_context(request: httpx.Request) -> None:
    """httpx request hook: send the current trace context as a traceparent header."""
    carrier: MutableMapping[str, str] = {}
    propagate.inject(carrier)
    request.headers.update(carrier)


class TraceContextMiddleware:
    """Continue the caller's trace: one SERVER span per request, under its traceparent."""

    def __init__(self, app: ASGIApp, skip_paths: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.skip_paths:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        tracer = trace.get_tracer(__name__)
        name = f"{scope['method']} {scope['path']}"
        with tracer.start_as_current_span(
            name,
            context=propagate.extract(headers),
            kind=SpanKind.SERVER,
            attributes={"http.request.method": scope["method"], "url.path": scope["path"]},
        ) as span:

            async def send_with_status(message: Message) -> None:
                if message["type"] == "http.response.start":
                    span.set_attribute("http.response.status_code", message["status"])
                await send(message)

            await self.app(scope, receive, send_with_status)
