from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from data import DATA_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SentinelAI"
    app_env: str = "development"
    log_level: str = "INFO"

    database_path: Path = Path("var/sentinel.db")
    data_dir: Path = DATA_DIR
    seed_incidents: bool = True

    api_keys: str = Field(
        default="",
        description="Comma separated role:sha256 pairs. See python -m auth.api_keys.",
    )
    tool_timeout_seconds: float = Field(default=5.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
