from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.enums import Environment, Severity
from core.models import Incident, IncidentCreate


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "checkout-api 5xx spike",
        "description": "Checkout requests are failing with 503.",
        "service": "checkout-api",
        "environment": Environment.PRODUCTION,
        "severity": Severity.SEV1,
        "timestamp": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    }
    payload.update(overrides)
    return payload


def test_incident_create_accepts_minimal_payload() -> None:
    incident = IncidentCreate.model_validate(make_payload())
    assert incident.symptoms == []
    assert incident.ground_truth_root_cause is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"service": "Checkout API"},
        {"timestamp": datetime(2026, 5, 1, 12, 0)},  # naive datetimes are ambiguous
        {"title": "x"},
        {"severity": "critical"},
        {"unexpected": "field"},
    ],
)
def test_incident_create_rejects_invalid_payload(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        IncidentCreate.model_validate(make_payload(**overrides))


def test_incident_id_format_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate({**make_payload(), "incident_id": "1234"})


def test_search_text_never_contains_ground_truth(incidents: list[Incident]) -> None:
    for incident in incidents:
        assert incident.ground_truth_root_cause
        assert incident.ground_truth_root_cause not in incident.search_text()
        assert incident.expected_remediation not in incident.search_text()
