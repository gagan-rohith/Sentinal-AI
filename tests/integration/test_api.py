from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from core.enums import Role
from core.models import Incident
from tests.conftest import DEMO_INCIDENT_ID, headers


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "incidents": "ok", "search": "ok"}


def test_app_starts_degraded_when_elasticsearch_is_down(settings: Settings) -> None:
    down = settings.model_copy(
        update={
            "search_backend": "elasticsearch",
            "elasticsearch_url": "http://127.0.0.1:1",
            # Windows takes about 2s to refuse a connection; keep the tool budget above that.
            "tool_timeout_seconds": 15.0,
        }
    )
    with TestClient(create_app(down)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["checks"]["search"].startswith("unavailable")

        search = client.get(
            "/tools/search", params={"q": "pool exhausted"}, headers=headers(Role.OPERATOR)
        )
        assert search.status_code == 503
        assert search.json()["error"]["code"] == "search_unavailable"

        # Everything that does not need search keeps working.
        assert client.get("/incidents", headers=headers(Role.VIEWER)).status_code == 200


def test_search_endpoint(client: TestClient) -> None:
    response = client.get(
        "/tools/search",
        params={"q": "connection pool exhausted", "source_type": "runbook", "top_k": 3},
        headers=headers(Role.OPERATOR),
    )
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 3
    assert hits[0]["parent_id"] == "runbook:postgres-connection-pool-exhaustion"
    assert {h["source_type"] for h in hits} == {"runbook"}


def test_search_endpoint_validates_query(client: TestClient) -> None:
    response = client.get("/tools/search", params={"q": "a"}, headers=headers(Role.OPERATOR))
    assert response.status_code == 422


def test_openapi_docs_load(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}" in paths


def test_missing_and_invalid_keys_are_rejected(client: TestClient) -> None:
    missing = client.get("/incidents")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthenticated"
    assert client.get("/incidents", headers={"X-API-Key": "nope"}).status_code == 401


def test_viewer_can_list_and_filter(client: TestClient) -> None:
    response = client.get("/incidents", params={"status": "open"}, headers=headers(Role.VIEWER))
    assert response.status_code == 200
    assert [i["incident_id"] for i in response.json()] == [DEMO_INCIDENT_ID]


def test_get_incident_and_not_found(client: TestClient) -> None:
    ok = client.get(f"/incidents/{DEMO_INCIDENT_ID}", headers=headers(Role.VIEWER))
    assert ok.status_code == 200
    assert ok.json()["service"] == "checkout-api"

    missing = client.get("/incidents/INC-9999", headers=headers(Role.VIEWER))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def _new_incident(demo: Incident) -> dict[str, object]:
    body = demo.model_dump(
        mode="json",
        exclude={"incident_id", "status", "relevant_runbook_ids"},
    )
    body["title"] = "payments timeouts during checkout"
    return body


def test_create_incident_requires_operator(client: TestClient, demo_incident: Incident) -> None:
    body = _new_incident(demo_incident)
    assert client.post("/incidents", json=body, headers=headers(Role.VIEWER)).status_code == 403

    created = client.post("/incidents", json=body, headers=headers(Role.OPERATOR))
    assert created.status_code == 201
    assert created.json()["incident_id"] == "INC-1061"

    duplicate = client.post("/incidents", json=body, headers=headers(Role.OPERATOR))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"]["existing_incident_id"] == "INC-1061"


def test_create_incident_validates_payload(client: TestClient) -> None:
    response = client.post("/incidents", json={"title": "x"}, headers=headers(Role.OPERATOR))
    assert response.status_code == 422


def test_tool_endpoints(client: TestClient, demo_incident: Incident) -> None:
    params = {"end_time": demo_incident.timestamp.isoformat()}
    for path in (
        "/tools/logs/checkout-api",
        "/tools/metrics/checkout-api",
        "/tools/deployments/checkout-api",
    ):
        response = client.get(path, params=params, headers=headers(Role.OPERATOR))
        assert response.status_code == 200, path

    logs = client.get("/tools/logs/checkout-api", params=params, headers=headers(Role.OPERATOR))
    assert logs.json()["error_count"] > 0


def test_tool_endpoints_enforce_permissions(client: TestClient) -> None:
    response = client.get("/tools/logs/checkout-api", headers=headers(Role.VIEWER))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_tool_endpoint_errors(client: TestClient) -> None:
    unknown = client.get("/tools/metrics/not-a-service", headers=headers(Role.OPERATOR))
    assert unknown.status_code == 404

    naive = client.get(
        "/tools/logs/checkout-api",
        params={"end_time": "2026-04-30T08:47:00"},
        headers=headers(Role.OPERATOR),
    )
    assert naive.status_code == 422
    assert naive.json()["error"]["code"] == "invalid_tool_input"
