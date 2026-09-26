from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api import health, incidents, tools
from app.config import Settings, get_settings
from app.container import Container
from core.exceptions import SentinelError

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await Container.create(settings)
        app.state.container = container
        log.info("startup", environment=settings.app_env)
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

    @app.exception_handler(SentinelError)
    async def sentinel_error_handler(request: Request, exc: SentinelError) -> JSONResponse:
        log.warning("request_failed", path=request.url.path, code=exc.code, error=exc.message)
        error = {"code": exc.code, "message": exc.message, "details": exc.details}
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder({"error": error}))

    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(tools.router)
    return app


app = create_app()
