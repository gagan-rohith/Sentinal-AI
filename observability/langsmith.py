"""Optional LangSmith tracing.

When LANGSMITH_API_KEY is configured, LangGraph traces every graph run (one span per
node), and the explicit spans around Claude calls and tool calls nest inside it. Without
a key nothing is sent anywhere and the spans are no-ops.

LangSmith reads its settings from the process environment and caches them, so this is
called once at startup, and tests pass their own mapping instead of os.environ.
"""

import os
from collections.abc import MutableMapping

import structlog
from pydantic import SecretStr

log = structlog.get_logger(__name__)


def configure_langsmith(
    api_key: SecretStr | None,
    project: str,
    env: MutableMapping[str, str] | None = None,
) -> bool:
    target = os.environ if env is None else env
    if api_key is None or not api_key.get_secret_value():
        return False
    target["LANGSMITH_TRACING"] = "true"
    target["LANGSMITH_API_KEY"] = api_key.get_secret_value()
    target["LANGSMITH_PROJECT"] = project
    log.info("langsmith_enabled", project=project)
    return True
