"""Request trace ids.

Every request gets a trace id: the caller's X-Trace-Id header when it is well formed,
otherwise a new one. It is bound into the logging context, returned in the response
header, and inherited by background tasks the request starts (asyncio copies context
into new tasks), so an analysis run's logs carry the id of the request that started it.
"""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from observability.metrics import record_http

TRACE_HEADER = "x-trace-id"
_VALID_TRACE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

log = structlog.get_logger("sentinel.http")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("trace_id")
    return str(value) if value else None


def accept_trace_id(value: str | None) -> str:
    return value if value and _VALID_TRACE_ID.fullmatch(value) else new_trace_id()


class TraceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        trace_id = accept_trace_id(headers.get(TRACE_HEADER))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        started = time.perf_counter()
        status = 500

        async def send_with_trace(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((TRACE_HEADER.encode(), trace_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            seconds = time.perf_counter() - started
            route = scope.get("route")
            # Route templates keep metric labels bounded; unmatched paths share one label.
            template = getattr(route, "path", "unmatched")
            record_http(scope["method"], template, status, seconds)
            log.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                route=template,
                status=status,
                duration_ms=round(seconds * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
