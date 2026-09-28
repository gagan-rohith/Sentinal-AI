import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from auth.permissions import AGENT_PRINCIPAL
from core.enums import RunStatus
from core.models import Incident
from graph.runner import IncidentAnalyzer
from graph.state import AgentDeps
from storage.db import Database
from storage.runs import RunRepository
from tools.tool_registry import ToolRegistry


@pytest.fixture
async def analyzer(registry: ToolRegistry) -> AsyncIterator[IncidentAnalyzer]:
    db = Database(":memory:")
    await db.connect()
    yield IncidentAnalyzer(AgentDeps(registry, None, AGENT_PRINCIPAL), RunRepository(db))
    await db.close()


async def test_completed_run_stores_report(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    run = await analyzer.start(demo_incident, "tester")
    finished = await analyzer.wait(run.run_id)
    assert finished.status is RunStatus.COMPLETED
    report = await analyzer.runs.report(run.run_id)
    assert report.run_id == run.run_id


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


async def test_synchronous_run_returns_final_state(
    analyzer: IncidentAnalyzer, demo_incident: Incident
) -> None:
    state = await analyzer.run(demo_incident)
    assert state["final_report"].incident_id == demo_incident.incident_id
