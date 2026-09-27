from collections import Counter

from core.enums import IncidentStatus, SourceType
from core.models import Incident
from data.loader import load_runbooks, load_service_docs
from retrieval.models import SearchDocument
from tests.conftest import DEMO_INCIDENT_ID


def test_document_counts_by_source(
    knowledge_docs: list[SearchDocument], incidents: list[Incident]
) -> None:
    counts = Counter(d.source_type for d in knowledge_docs)
    resolved = [i for i in incidents if i.status is IncidentStatus.RESOLVED]
    assert counts[SourceType.RUNBOOK] == 8 * len(load_runbooks())
    assert counts[SourceType.SERVICE_DOC] == len(load_service_docs())
    assert counts[SourceType.INCIDENT] == len(resolved)
    assert counts[SourceType.LOG] == len(resolved)


def test_document_ids_are_unique(knowledge_docs: list[SearchDocument]) -> None:
    ids = [d.document_id for d in knowledge_docs]
    assert len(ids) == len(set(ids))


def test_open_incident_is_not_indexed(knowledge_docs: list[SearchDocument]) -> None:
    assert all(d.incident_id != DEMO_INCIDENT_ID for d in knowledge_docs)


def test_runbook_chunks_share_parent_and_keep_section(
    knowledge_docs: list[SearchDocument],
) -> None:
    chunks = [
        d for d in knowledge_docs if d.parent_id == "runbook:postgres-connection-pool-exhaustion"
    ]
    assert {c.metadata["section"] for c in chunks} >= {"Symptoms", "Remediation", "Risk notes"}
    assert all(c.metadata["actions"] == ["restart_service"] for c in chunks)
    remediation = next(c for c in chunks if c.metadata["section"] == "Remediation")
    assert "PgBouncer" in remediation.text


def test_incident_documents_carry_postmortem_knowledge(
    knowledge_docs: list[SearchDocument], incidents: list[Incident]
) -> None:
    resolved = next(i for i in incidents if i.status is IncidentStatus.RESOLVED)
    document = next(
        d for d in knowledge_docs if d.document_id == f"incident:{resolved.incident_id}"
    )
    assert f"Root cause: {resolved.ground_truth_root_cause}" in document.text
    assert document.metadata["root_cause_category"] == resolved.root_cause_category


def test_log_snippets_hold_error_patterns(knowledge_docs: list[SearchDocument]) -> None:
    logs = [d for d in knowledge_docs if d.source_type is SourceType.LOG]
    assert all(line.startswith("[") for d in logs for line in d.text.splitlines())
    assert all(d.incident_id for d in logs)
