import uvicorn

from critic_service.server import CriticSettings, create_app
from observability.logging import configure_logging
from observability.otel import configure_tracing


def main() -> None:
    settings = CriticSettings()
    configure_logging(settings.log_level, settings.log_format)
    configure_tracing("sentinel-critic")
    uvicorn.run(create_app(settings), host=settings.critic_host, port=settings.critic_port)


if __name__ == "__main__":
    main()
