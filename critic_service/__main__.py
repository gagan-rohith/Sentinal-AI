import uvicorn

from critic_service.server import CriticSettings, create_app
from observability.logging import configure_logging


def main() -> None:
    settings = CriticSettings()
    configure_logging(settings.log_level, settings.log_format)
    uvicorn.run(create_app(settings), host=settings.critic_host, port=settings.critic_port)


if __name__ == "__main__":
    main()
