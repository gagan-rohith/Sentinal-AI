import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from auth.permissions import AGENT_PRINCIPAL, Principal
from core.enums import ApprovalStatus, Role, RunStatus
from core.exceptions import InvalidStateError, UnauthorizedActionError
from core.models import Incident
from graph.checkpoint import open_checkpointer, serializer
from graph.runner import IncidentAnalyzer
from graph.state import AgentDeps
from retrieval.hybrid_search import HybridSearcher
from storage.approvals import ApprovalStore
from storage.db import Database
from storage.runs import RunRepository
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import build_default_registry

ADMIN = Principal(subject="alice", role=Role.ADMIN, auth_method="test")
OPERATOR = Principal(subject="bob", role=Role.OPERATOR, auth_method="test")
VIEWER = Principal(subject="carol", role=Role.VIEWER, auth_method="test")


def make_analyzer(
    db: Database, backend: SimulatedOpsBackend, searcher: HybridSearcher, checkpointer: Any
) -> IncidentAnalyzer:
    # The real wiring: the approval store is also the registry's approval verifier.
    approvals = ApprovalStore(db)
    registry = build_default_registry(backend, TicketStore(), searcher, approvals=approvals)
    deps = AgentDeps(registry, None, AGENT_PRINCIPAL)
    return IncidentAnalyzer(deps, RunRepository(db), approvals, checkpointer)


@pytest.fixture
async def analyzer(
    backend: SimulatedOpsBackend, searcher: HybridSearcher
) -> AsyncIterator[IncidentAnalyzer]:
    db = Database(":memory:")
    await db.connect()
    yield make_analyzer(db, backend, searcher, InMemorySaver(serde=serializer()))
    await db.close()


async def paused_run(analyzer: IncidentAnalyzer, incident: Incident) -> str:
    run = await analyzer.start(incident, "tester")
    paused = await analyzer.wait(run.run_id)
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.stage == "human_approval"
    return run.run_id


async def test_run_pauses_with_a_pending_approval(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    approval = await analyzer.approvals.for_run(run_id)
    assert approval.status is ApprovalStatus.PENDING
    assert [(a.tool, a.arguments) for a in approval.request.actions] == [
        ("restart_service", {"service": "checkout-api"})
    ]
    with pytest.raises(InvalidStateError):
        await analyzer.runs.report(run_id)


async def test_admin_approval_executes_once(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    await analyzer.approve(run_id, ADMIN, "go ahead")
    finished = await analyzer.wait(run_id)
    assert finished.status is RunStatus.COMPLETED

    report = await analyzer.runs.report(run_id)
    assert report.approval_status is ApprovalStatus.APPROVED
    assert [a.status for a in report.executed_actions] == ["succeeded"]
    approval = await analyzer.approvals.for_run(run_id)
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.decided_by == "alice"
    assert len(approval.consumed) == 1

    # The approval is single use: replaying the same action is refused.
    replay = await analyzer.approvals.verify(
        approval.approval_id, "restart_service", {"service": "checkout-api"}
    )
    assert replay is False


async def test_rejection_finishes_without_executing(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    await analyzer.reject(run_id, OPERATOR, "not during peak traffic")
    await analyzer.wait(run_id)
    report = await analyzer.runs.report(run_id)
    assert report.approval_status is ApprovalStatus.REJECTED
    assert report.executed_actions == []
    assert report.approval is not None
    assert report.approval.comment == "not during peak traffic"


async def test_operator_cannot_approve(analyzer: IncidentAnalyzer, demo_incident: Incident) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    with pytest.raises(UnauthorizedActionError):
        await analyzer.approve(run_id, OPERATOR, None)
    with pytest.raises(UnauthorizedActionError):
        await analyzer.reject(run_id, VIEWER, "no")
    assert (await analyzer.runs.get(run_id)).status is RunStatus.AWAITING_APPROVAL


async def test_second_decision_is_rejected(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    await analyzer.approve(run_id, ADMIN, None)
    with pytest.raises(InvalidStateError):
        await analyzer.approve(run_id, ADMIN, None)
    await analyzer.wait(run_id)
    with pytest.raises(InvalidStateError, match="not awaiting approval"):
        await analyzer.reject(run_id, ADMIN, "too late")


async def test_concurrent_decisions_only_one_wins(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run_id = await paused_run(analyzer, demo_incident)
    results = await asyncio.gather(
        analyzer.approvals.decide(run_id, approved=True, principal=ADMIN, comment=None),
        analyzer.approvals.decide(run_id, approved=False, principal=ADMIN, comment="no"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, InvalidStateError) for r in results) == 1


async def test_safe_run_completes_without_approval(
    analyzer: IncidentAnalyzer, incidents: list[Incident]
) -> None:
    incident = next(i for i in incidents if i.root_cause_category == "k8s_oom_killed")
    run = await analyzer.start(incident, "tester")
    finished = await analyzer.wait(run.run_id)
    assert finished.status is RunStatus.COMPLETED


async def test_approval_survives_a_restart(
    tmp_path: Path,
    backend: SimulatedOpsBackend,
    searcher: HybridSearcher,
    demo_incident: Incident,
) -> None:
    path = tmp_path / "sentinel.db"
    db = Database(path)
    await db.connect()
    saver = await open_checkpointer(path)
    first = make_analyzer(db, backend, searcher, saver)
    run_id = await paused_run(first, demo_incident)
    await first.shutdown()
    await saver.conn.close()
    await db.close()

    # A fresh process: new connections, new graph, same files.
    db = Database(path)
    await db.connect()
    saver = await open_checkpointer(path)
    second = make_analyzer(db, backend, searcher, saver)
    try:
        await second.approve(run_id, ADMIN, "approved after restart")
        finished = await second.wait(run_id)
        assert finished.status is RunStatus.COMPLETED
        report = await second.runs.report(run_id)
        assert [a.status for a in report.executed_actions] == ["succeeded"]
    finally:
        await saver.conn.close()
        await db.close()


async def test_typed_failure_is_recorded(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    ghost = demo_incident.model_copy(update={"service": "ghost-service"})
    run = await analyzer.start(ghost, "tester")
    finished = await analyzer.wait(run.run_id)
    assert finished.status is RunStatus.FAILED
    assert finished.error_code == "missing_incident_data"


async def test_unexpected_crash_is_recorded(
    analyzer: IncidentAnalyzer, demo_incident: Incident, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(analyzer.graph, "astream", explode)
    run = await analyzer.start(demo_incident, "tester")
    finished = await analyzer.wait(run.run_id)
    assert finished.status is RunStatus.FAILED
    assert (finished.error_code, finished.error_message) == ("internal_error", "RuntimeError: boom")


async def test_shutdown_marks_running_runs_cancelled(
    analyzer: IncidentAnalyzer, demo_incident: Incident, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(*_: Any, **__: Any) -> Any:
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    monkeypatch.setattr(analyzer.graph, "astream", hang)
    run = await analyzer.start(demo_incident, "tester")
    await asyncio.sleep(0.05)
    await analyzer.shutdown()
    cancelled = await analyzer.runs.get(run.run_id)
    assert cancelled.status is RunStatus.FAILED
    assert cancelled.error_code == "cancelled"
