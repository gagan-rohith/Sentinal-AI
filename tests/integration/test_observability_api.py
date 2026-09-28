import time

from fastapi.testclient import TestClient

from core.enums import Role
from tests.conftest import DEMO_INCIDENT_ID, headers


def test_every_response_has_a_trace_id(client: TestClient) -> None:
    generated = client.get("/health")
    assert len(generated.headers["x-trace-id"]) == 32

    echoed = client.get("/health", headers={"X-Trace-Id": "caller-trace-0001"})
    assert echoed.headers["x-trace-id"] == "caller-trace-0001"

    rejected = client.get("/health", headers={"X-Trace-Id": "no spaces allowed"})
    assert rejected.headers["x-trace-id"] != "no spaces allowed"


def test_errors_include_the_trace_id(client: TestClient) -> None:
    response = client.get(
        "/incidents/INC-9999",
        headers={**headers(Role.VIEWER), "X-Trace-Id": "error-trace-0001"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["trace_id"] == "error-trace-0001"


def test_run_report_keeps_the_starting_request_trace_id(client: TestClient) -> None:
    started = client.post(
        f"/agents/analyze/{DEMO_INCIDENT_ID}",
        headers={**headers(Role.OPERATOR), "X-Trace-Id": "analysis-trace-01"},
    )
    run_id = started.json()["run_id"]
    for _ in range(300):
        status = client.get(f"/agents/status/{run_id}", headers=headers(Role.VIEWER)).json()
        if status["status"] == "awaiting_approval":
            break
        time.sleep(0.05)
    client.post(f"/agents/{run_id}/reject", json={"reason": "not now"},
                headers=headers(Role.OPERATOR))  # fmt: skip
    for _ in range(300):
        report = client.get(f"/agents/{run_id}/report", headers=headers(Role.VIEWER))
        if report.status_code == 200:
            break
        time.sleep(0.05)
    assert report.json()["trace_id"] == "analysis-trace-01"


def test_metrics_endpoint_exposes_counters(client: TestClient) -> None:
    client.get("/tools/metrics/checkout-api", headers=headers(Role.OPERATOR))
    body = client.get("/metrics").text
    assert 'sentinel_http_requests_total{method="GET",route="/tools/metrics/{service}"' in body
    assert 'sentinel_tool_calls_total{status="success",tool="get_service_metrics"}' in body
    assert "sentinel_http_request_duration_seconds_bucket" in body
    # Unmatched paths share one label instead of creating a series per URL.
    client.get("/definitely/not/a/route")
    assert 'route="unmatched"' in client.get("/metrics").text
