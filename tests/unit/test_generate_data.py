import re
from collections import Counter

from core.enums import IncidentStatus
from core.models import Incident
from data.generate_data import Generator
from data.loader import load_metrics, load_runbooks, load_service_docs
from data.scenarios import SCENARIOS
from tests.conftest import DEMO_INCIDENT_ID

REQUIRED_RUNBOOK_SECTIONS = {
    "Symptoms",
    "Likely causes",
    "Diagnostic steps",
    "Commands",
    "Remediation",
    "Rollback",
    "Risk notes",
    "Escalation",
}


def test_generator_is_deterministic() -> None:
    first = Generator(seed=7).build()
    second = Generator(seed=7).build()
    assert [i.model_dump() for i in first.incidents] == [i.model_dump() for i in second.incidents]
    assert len(first.logs) == len(second.logs)


def test_committed_dataset_matches_generator(incidents: list[Incident]) -> None:
    regenerated = Generator(seed=42).build().incidents
    assert [i.model_dump(mode="json") for i in regenerated] == [
        i.model_dump(mode="json") for i in incidents
    ]


def test_dataset_covers_every_scenario(incidents: list[Incident]) -> None:
    assert len(incidents) >= 50
    categories = Counter(i.root_cause_category for i in incidents)
    assert set(categories) == {s.category for s in SCENARIOS}
    assert all(count == 3 for count in categories.values())


def test_only_the_demo_incident_is_open(incidents: list[Incident]) -> None:
    open_ids = [i.incident_id for i in incidents if i.status is IncidentStatus.OPEN]
    assert open_ids == [DEMO_INCIDENT_ID]
    assert max(incidents, key=lambda i: i.timestamp).incident_id == DEMO_INCIDENT_ID


def test_incident_runbook_references_exist(incidents: list[Incident]) -> None:
    runbook_ids = {r.runbook_id for r in load_runbooks()}
    for incident in incidents:
        assert incident.relevant_runbook_ids
        assert set(incident.relevant_runbook_ids) <= runbook_ids


def test_runbooks_have_required_sections() -> None:
    runbooks = load_runbooks()
    assert len(runbooks) >= 15
    for runbook in runbooks:
        sections = set(re.findall(r"^## (.+)$", runbook.body, flags=re.MULTILINE))
        assert sections >= REQUIRED_RUNBOOK_SECTIONS, runbook.runbook_id


def test_every_incident_service_has_a_doc(incidents: list[Incident]) -> None:
    documented = {d.service for d in load_service_docs()}
    assert {i.service for i in incidents} <= documented


def test_hard_limit_metrics_never_exceed_ceiling() -> None:
    pool = [s for s in load_metrics() if s.name == "db_connections_in_use"]
    assert pool
    assert all(p.value <= 100 for s in pool for p in s.points)
