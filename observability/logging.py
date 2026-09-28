"""Structured logging.

Both structlog loggers (application code) and standard library loggers (uvicorn,
httpx, the MCP SDK) render through the same processors, so every line has the same
shape: timestamp, level, event, and any bound context such as trace_id or run_id.
"""

import logging
import sys
from typing import Any, Literal, TextIO

import structlog

LogFormat = Literal["json", "console"]


def configure_logging(
    level: str = "INFO", fmt: LogFormat = "json", stream: TextIO | None = None
) -> None:
    stream = stream or sys.stdout
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric_level)
