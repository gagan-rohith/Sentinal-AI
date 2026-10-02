from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api import agents, evaluations, health, incidents, metrics, tools
from app.config import Settings, get_settings
from app.container import Container
from core.exceptions import SentinelError
from observability.langsmith import configure_langsmith
from observability.logging import configure_logging
from observability.otel import configure_tracing
from observability.tracing import TraceMiddleware, current_trace_id

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Run with: uvicorn --factory app.main:create_app

    Building the app on demand, not at import time, keeps importing this module free of
    side effects such as reading .env or switching on tracing.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    langsmith_enabled = configure_langsmith(settings.langsmith_api_key, settings.langsmith_project)
    otel_enabled = configure_tracing("sentinel-api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await Container.create(settings)
        app.state.container = container
        log.info(
            "startup",
            environment=settings.app_env,
            langsmith=langsmith_enabled,
            opentelemetry=otel_enabled,
        )
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Multi-agent SRE incident response platform.",
        lifespan=lifespan,
    )
    app.add_middleware(TraceMiddleware)

    @app.exception_handler(SentinelError)
    async def sentinel_error_handler(request: Request, exc: SentinelError) -> JSONResponse:
        log.warning("request_failed", path=request.url.path, code=exc.code, error=exc.message)
        # The trace id lets a caller point at the exact request in the logs.
        error = {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "trace_id": current_trace_id(),
        }
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder({"error": error}))

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(incidents.router)
    app.include_router(tools.router)
    app.include_router(agents.router)
    app.include_router(evaluations.router)
    return app
