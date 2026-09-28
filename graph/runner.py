import asyncio
from typing import Any, cast

import structlog

from core.enums import RunStatus
from core.exceptions import SentinelError
from core.models import Incident
from graph.incident_graph import RECURSION_LIMIT, build_incident_graph
from graph.state import AgentDeps, IncidentState, Stage
from storage.runs import RunRecord, RunRepository

log = structlog.get_logger(__name__)


class IncidentAnalyzer:
    """Starts graph runs in the background and records their progress."""

    def __init__(self, deps: AgentDeps, runs: RunRepository) -> None:
        self.graph = build_incident_graph(deps)
        self.runs = runs
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self, incident: Incident, requested_by: str) -> RunRecord:
        run = await self.runs.create(incident.incident_id, requested_by)
        task = asyncio.create_task(self._execute(run.run_id, incident), name=run.run_id)
        self._tasks[run.run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run.run_id, None))
        return run

    async def wait(self, run_id: str) -> RunRecord:
        task = self._tasks.get(run_id)
        if task is not None:
            await task
        return await self.runs.get(run_id)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, incident: Incident, run_id: str = "adhoc") -> IncidentState:
        """Run the graph to completion in the caller's task. Used by the benchmark."""
        initial: IncidentState = {"run_id": run_id, "incident": incident, "stage": Stage.START}
        result = await self.graph.ainvoke(initial, {"recursion_limit": RECURSION_LIMIT})
        return cast(IncidentState, result)

    async def _execute(self, run_id: str, incident: Incident) -> None:
        await self.runs.update(run_id, status=RunStatus.RUNNING, stage="supervisor")
        initial: IncidentState = {"run_id": run_id, "incident": incident, "stage": Stage.START}
        final: dict[str, Any] = {}
        try:
            async for mode, chunk in self.graph.astream(
                initial,
                {"recursion_limit": RECURSION_LIMIT},
                stream_mode=["updates", "values"],
            ):
                if not isinstance(chunk, dict):
                    continue
                if mode == "values":
                    final = chunk
                    continue
                for node, update in chunk.items():
                    retries = update.get("retry_count") if isinstance(update, dict) else None
                    await self.runs.update(run_id, stage=node, retry_count=retries)
            await self.runs.complete(run_id, final["final_report"])
            log.info("run_completed", run_id=run_id, incident_id=incident.incident_id)
        except asyncio.CancelledError:
            await self.runs.fail(run_id, "cancelled", "the service shut down during the run")
            raise
        except SentinelError as exc:
            log.warning("run_failed", run_id=run_id, code=exc.code, error=exc.message)
            await self.runs.fail(run_id, exc.code, exc.message)
        except Exception as exc:
            # A background task has no caller to raise to; record the failure and keep
            # the traceback in the logs.
            log.exception("run_crashed", run_id=run_id)
            await self.runs.fail(run_id, "internal_error", f"{type(exc).__name__}: {exc}")
