import time
from typing import Any

from fastapi.testclient import TestClient

from core.enums import Role
from tests.conftest import headers


def wait_idle(client: TestClient, timeout_s: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status: dict[str, Any] = client.get("/evals/status", headers=headers(Role.VIEWER)).json()
        if status["state"] != "running":
            return status
        time.sleep(0.1)
    raise AssertionError("benchmark did not finish")


def test_latest_is_404_before_any_run(client: TestClient) -> None:
    response = client.get("/evals/latest", headers=headers(Role.VIEWER))
    assert response.status_code == 404


def test_run_and_fetch_latest(client: TestClient) -> None:
    viewer = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.VIEWER))
    assert viewer.status_code == 403

    started = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.OPERATOR))
    assert started.status_code == 202
    assert started.json()["state"] == "running"

    again = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.OPERATOR))
    assert again.status_code == 409

    assert wait_idle(client)["state"] == "idle"
    latest = client.get("/evals/latest", headers=headers(Role.VIEWER))
    assert latest.status_code == 200
    body = latest.json()
    assert body["setup"]["incident_cases"] == 2
    assert body["setup"]["llm_mode"] == "heuristic"


def test_llm_benchmark_needs_admin(client: TestClient) -> None:
    response = client.post(
        "/evals/run", json={"provider": "anthropic", "limit": 1}, headers=headers(Role.OPERATOR)
    )
    assert response.status_code == 403
    assert "only admins" in response.json()["error"]["message"]
