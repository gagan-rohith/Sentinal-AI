import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.enums import Role
from tests.conftest import DEMO_INCIDENT_ID, headers

SAFE_INCIDENT_ID = "INC-1003"  # OOM incident: its plan has no destructive action


def wait_for(
    client: TestClient, run_id: str, *statuses: str, timeout_s: float = 30.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run: dict[str, Any] = client.get(
            f"/agents/status/{run_id}", headers=headers(Role.VIEWER)
        ).json()
        if run["status"] in statuses:
            return run
        if run["status"] == "failed":
            pytest.fail(f"run {run_id} failed: {run['error_code']}: {run['error_message']}")
        time.sleep(0.05)
    pytest.fail(f"run {run_id} did not reach {statuses} in {timeout_s}s")


def start(client: TestClient, incident_id: str = DEMO_INCIDENT_ID) -> str:
    response = client.post(f"/agents/analyze/{incident_id}", headers=headers(Role.OPERATOR))
    assert response.status_code == 202
    run_id: str = response.json()["run_id"]
    return run_id


def test_analysis_requires_operator(client: TestClient) -> None:
    response = client.post(f"/agents/analyze/{DEMO_INCIDENT_ID}", headers=headers(Role.VIEWER))
    assert response.status_code == 403


def test_approve_flow_end_to_end(client: TestClient) -> None:
    run_id = start(client)
    paused = wait_for(client, run_id, "awaiting_approval", "failed")
    assert paused["status"] == "awaiting_approval", paused

    approval = client.get(f"/agents/{run_id}/approval", headers=headers(Role.VIEWER)).json()
    assert approval["status"] == "pending"
    assert approval["request"]["actions"][0]["tool"] == "restart_service"
    assert approval["request"]["root_cause"] == "PostgreSQL connection pool exhaustion"

    early = client.get(f"/agents/{run_id}/report", headers=headers(Role.VIEWER))
    assert early.status_code == 409

    denied = client.post(f"/agents/{run_id}/approve", headers=headers(Role.OPERATOR))
    assert denied.status_code == 403

    approved = client.post(
        f"/agents/{run_id}/approve", json={"comment": "pool confirmed"}, headers=headers(Role.ADMIN)
    )
    assert approved.status_code == 202
    again = client.post(f"/agents/{run_id}/approve", headers=headers(Role.ADMIN))
    assert again.status_code == 409

    done = wait_for(client, run_id, "completed", "failed")
    assert done["status"] == "completed", done
    report = client.get(f"/agents/{run_id}/report", headers=headers(Role.VIEWER)).json()
    assert report["approval_status"] == "approved"
    assert report["approval"]["comment"] == "pool confirmed"
    assert [a["status"] for a in report["executed_actions"]] == ["succeeded"]
    assert report["selected_root_cause"]["category"] == "postgres_pool_exhaustion"


def test_reject_flow(client: TestClient) -> None:
    run_id = start(client)
    wait_for(client, run_id, "awaiting_approval")

    viewer = client.post(
        f"/agents/{run_id}/reject", json={"reason": "no"}, headers=headers(Role.VIEWER)
    )
    assert viewer.status_code == 403
    missing_reason = client.post(
        f"/agents/{run_id}/reject", json={}, headers=headers(Role.OPERATOR)
    )
    assert missing_reason.status_code == 422

    rejected = client.post(
        f"/agents/{run_id}/reject",
        json={"reason": "wait for traffic to drop"},
        headers=headers(Role.OPERATOR),
    )
    assert rejected.status_code == 202
    wait_for(client, run_id, "completed")
    report = client.get(f"/agents/{run_id}/report", headers=headers(Role.VIEWER)).json()
    assert report["approval_status"] == "rejected"
    assert report["executed_actions"] == []


def test_safe_plan_completes_without_approval(client: TestClient) -> None:
    run_id = start(client, SAFE_INCIDENT_ID)
    run = wait_for(client, run_id, "completed", "failed", "awaiting_approval")
    assert run["status"] == "completed"
    missing = client.get(f"/agents/{run_id}/approval", headers=headers(Role.VIEWER))
    assert missing.status_code == 404
    approve = client.post(f"/agents/{run_id}/approve", headers=headers(Role.ADMIN))
    assert approve.status_code == 409


def test_second_analysis_while_running_is_rejected(client: TestClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    active = client.portal.call(container.analyzer.runs.create, DEMO_INCIDENT_ID, "someone")
    response = client.post(f"/agents/analyze/{DEMO_INCIDENT_ID}", headers=headers(Role.OPERATOR))
    assert response.status_code == 409
    assert response.json()["error"]["details"]["run_id"] == active.run_id


def test_unknown_run_and_incident(client: TestClient) -> None:
    assert (
        client.get("/agents/status/run-000000000000", headers=headers(Role.VIEWER)).status_code
        == 404
    )
    assert (
        client.post("/agents/analyze/INC-9999", headers=headers(Role.OPERATOR)).status_code == 404
    )
