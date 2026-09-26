from datetime import timedelta

import pytest

from core.enums import IncidentStatus, Severity
from core.exceptions import DuplicateIncidentError, NotFoundError
from core.models import Incident, IncidentCreate
from storage.incidents import IncidentRepository, fingerprint


def as_create(incident: Incident, **overrides: object) -> IncidentCreate:
    data = incident.model_dump(exclude={"incident_id", "status", "relevant_runbook_ids"})
    data.update(overrides)
    return IncidentCreate.model_validate(data)


def test_fingerprint_ignores_case_and_whitespace() -> None:
    assert fingerprint("a-svc", "production", "DB  Down") == fingerprint(
        "a-svc", "production", "db down"
    )


async def test_seed_and_get(repo: IncidentRepository, incidents: list[Incident]) -> None:
    assert await repo.seed(incidents) == len(incidents)
    assert await repo.count() == len(incidents)
    assert await repo.get(incidents[0].incident_id) == incidents[0]


async def test_seed_is_idempotent(repo: IncidentRepository, incidents: list[Incident]) -> None:
    await repo.seed(incidents)
    await repo.seed(incidents)
    assert await repo.count() == len(incidents)


async def test_get_missing_raises(repo: IncidentRepository) -> None:
    with pytest.raises(NotFoundError):
        await repo.get("INC-9999")


async def test_list_filters_and_orders(repo: IncidentRepository, incidents: list[Incident]) -> None:
    await repo.seed(incidents)
    checkout = await repo.list_incidents(service="checkout-api")
    assert checkout
    assert all(i.service == "checkout-api" for i in checkout)
    assert [i.timestamp for i in checkout] == sorted((i.timestamp for i in checkout), reverse=True)

    open_incidents = await repo.list_incidents(status=IncidentStatus.OPEN)
    assert [i.status for i in open_incidents] == [IncidentStatus.OPEN]

    sev1 = await repo.list_incidents(severity=Severity.SEV1, limit=2)
    assert len(sev1) == 2


async def test_create_assigns_next_id(repo: IncidentRepository, incidents: list[Incident]) -> None:
    await repo.seed(incidents)
    created = await repo.create(
        as_create(incidents[0], title="brand new incident title", timestamp=incidents[0].timestamp)
    )
    assert created.incident_id == "INC-1061"
    assert created.status is IncidentStatus.OPEN


async def test_duplicate_open_incident_rejected(
    repo: IncidentRepository, demo_incident: Incident
) -> None:
    await repo.seed([demo_incident])
    with pytest.raises(DuplicateIncidentError) as exc_info:
        await repo.create(
            as_create(demo_incident, timestamp=demo_incident.timestamp + timedelta(minutes=10))
        )
    assert exc_info.value.details["existing_incident_id"] == demo_incident.incident_id


async def test_same_title_outside_window_is_not_duplicate(
    repo: IncidentRepository, demo_incident: Incident
) -> None:
    await repo.seed([demo_incident])
    created = await repo.create(
        as_create(demo_incident, timestamp=demo_incident.timestamp + timedelta(hours=3))
    )
    assert created.incident_id != demo_incident.incident_id


async def test_resolved_incident_is_not_duplicate(
    repo: IncidentRepository, incidents: list[Incident]
) -> None:
    resolved = next(i for i in incidents if i.status is IncidentStatus.RESOLVED)
    await repo.seed([resolved])
    created = await repo.create(as_create(resolved))
    assert created.incident_id != resolved.incident_id
