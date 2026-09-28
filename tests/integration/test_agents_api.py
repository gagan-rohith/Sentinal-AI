import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.enums import Role
from tests.conftest import DEMO_INCIDENT_ID, headers


def wait_for(client: TestClient, run_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run: dict[str, Any] = client.get(
            f"/agents/status/{run_id}", headers=headers(Role.VIEWER)
        ).json()
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.05)
    pytest.fail(f"run {run_id} did not finish in {timeout_s}s")


def test_analysis_requires_operator(client: TestClient) -> None:
    response = client.post(f"/agents/analyze/{DEMO_INCIDENT_ID}", headers=headers(Role.VIEWER))
    assert response.status_code == 403


def test_analyze_demo_incident_end_to_end(client: TestClient) -> None:
    started = client.post(f"/agents/analyze/{DEMO_INCIDENT_ID}", headers=headers(Role.OPERATOR))
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    assert started.json()["status"] == "queued"

    run = wait_for(client, run_id)
    assert run["status"] == "completed", run
    assert run["stage"] == "done"

    report = client.get(f"/agents/{run_id}/report", headers=headers(Role.VIEWER))
    assert report.status_code == 200
    body = report.json()
    assert body["selected_root_cause"]["category"] == "postgres_pool_exhaustion"
    assert body["approval_status"] == "pending"
    assert body["remediation_plan"]["approval_required"] is True
    assert body["mode"] == "heuristic"


def test_second_analysis_while_running_is_rejected(client: TestClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    active = client.portal.call(container.analyzer.runs.create, DEMO_INCIDENT_ID, "someone")
    response = client.post(f"/agents/analyze/{DEMO_INCIDENT_ID}", headers=headers(Role.OPERATOR))
    assert response.status_code == 409
    assert response.json()["error"]["details"]["run_id"] == active.run_id

    early = client.get(f"/agents/{active.run_id}/report", headers=headers(Role.VIEWER))
    assert early.status_code == 409
    assert early.json()["error"]["details"]["status"] == "queued"


def test_unknown_run_and_incident(client: TestClient) -> None:
    assert (
        client.get("/agents/status/run-000000000000", headers=headers(Role.VIEWER)).status_code
        == 404
    )
    assert (
        client.post("/agents/analyze/INC-9999", headers=headers(Role.OPERATOR)).status_code == 404
    )
