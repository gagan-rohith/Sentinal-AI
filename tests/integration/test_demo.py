from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo import DemoError, Narrator, demo_settings, run_demo
from app.main import create_app
from core.enums import Role
from tests.conftest import KEYS

DEMO_KEYS = {"operator": KEYS[Role.OPERATOR], "admin": KEYS[Role.ADMIN]}


def test_demo_walks_through_inc_1060(settings: Settings) -> None:
    lines: list[str] = []
    with TestClient(create_app(settings)) as client:
        report = run_demo(client, DEMO_KEYS, Narrator(out=lines.append))

    text = "\n".join(lines)
    assert report["selected_root_cause"]["title"] == "PostgreSQL connection pool exhaustion"
    assert "Refused: 403" in text
    assert "Approving a second time is refused: 409" in text
    assert "[ruled out] Regression introduced by deployment" in text
    assert "restart_service: succeeded" in text
    assert KEYS[Role.ADMIN] not in text


class _Response:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def json(self) -> dict[str, Any]:
        return self.body


class _NoSearchClient:
    def get(self, path: str, **_: Any) -> _Response:
        return _Response({"status": "degraded", "checks": {"search": "unavailable"}})


def test_demo_stops_when_search_is_down() -> None:
    with pytest.raises(DemoError, match="--memory"):
        run_demo(_NoSearchClient(), DEMO_KEYS, Narrator(out=lambda _: None))  # type: ignore[arg-type]


def test_demo_settings_isolate_state(tmp_path: Path) -> None:
    settings = demo_settings(tmp_path, memory=True, keys=DEMO_KEYS)
    assert settings.database_path == tmp_path / "demo.db"
    assert settings.search_backend == "memory"
    assert settings.langsmith_api_key is None
    assert KEYS[Role.ADMIN] not in settings.api_keys
    assert settings.api_keys.startswith("operator:")
