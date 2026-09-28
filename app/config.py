from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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

    search_backend: Literal["elasticsearch", "memory"] = "elasticsearch"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "sentinel-knowledge"
    # Build the index at startup when it is empty.
    auto_index: bool = True
    embedding_provider: Literal["sentence-transformers", "hash"] = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str | None = None

    # auto: Claude when ANTHROPIC_API_KEY is set, deterministic heuristics otherwise.
    llm_provider: Literal["auto", "anthropic", "heuristic"] = "auto"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    max_critic_retries: int = Field(default=3, ge=0, le=10)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
