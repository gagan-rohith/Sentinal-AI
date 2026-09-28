import asyncio
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from agents.schemas import ApprovalRequest
from auth.permissions import Principal
from auth.rbac import Permission
from core.enums import RunStatus
from core.exceptions import InvalidStateError, SentinelError
from core.models import Incident
from graph.incident_graph import RECURSION_LIMIT, build_incident_graph
from graph.state import AgentDeps, IncidentState, Stage
from storage.approvals import ApprovalStore
from storage.runs import RunRecord, RunRepository

log = structlog.get_logger(__name__)

GraphInput = IncidentState | Command[Any]


def _config(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}


class IncidentAnalyzer:
    """Runs incident graphs in the background, pauses them for approval and resumes them.

    Paused runs live in the checkpointer, so an approval can arrive after a restart.
    """

    def __init__(
        self,
        deps: AgentDeps,
        runs: RunRepository,
        approvals: ApprovalStore,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> None:
        self.graph = build_incident_graph(deps, checkpointer)
        self.runs = runs
        self.approvals = approvals
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self, incident: Incident, requested_by: str) -> RunRecord:
        run = await self.runs.create(incident.incident_id, requested_by)
        initial: IncidentState = {"run_id": run.run_id, "incident": incident, "stage": Stage.START}
        self._spawn(run.run_id, initial)
        return run

    async def approve(self, run_id: str, principal: Principal, comment: str | None) -> RunRecord:
        principal.require(Permission.EXECUTE_REMEDIATION)
        return await self._decide(run_id, principal, approved=True, comment=comment)

    async def reject(self, run_id: str, principal: Principal, reason: str) -> RunRecord:
        principal.require(Permission.REJECT_REMEDIATION)
        return await self._decide(run_id, principal, approved=False, comment=reason)

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

    async def _decide(
        self, run_id: str, principal: Principal, *, approved: bool, comment: str | None
    ) -> RunRecord:
        run = await self.runs.get(run_id)
        if run.status is not RunStatus.AWAITING_APPROVAL:
            raise InvalidStateError(
                f"run {run_id} is {run.status}, not awaiting approval",
                details={"status": run.status.value},
            )
        decision = await self.approvals.decide(
            run_id, approved=approved, principal=principal, comment=comment
        )
        next_stage = "action_execution" if approved else "postmortem"
        await self.runs.update(run_id, status=RunStatus.RUNNING, stage=next_stage)
        log.info("approval_decided", run_id=run_id, approved=approved, by=principal.subject)
        self._spawn(run_id, Command(resume=decision.model_dump(mode="json")))
        return await self.runs.get(run_id)

    def _spawn(self, run_id: str, graph_input: GraphInput) -> None:
        task = asyncio.create_task(self._drive(run_id, graph_input), name=run_id)
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    async def _drive(self, run_id: str, graph_input: GraphInput) -> None:
        config = _config(run_id)
        await self.runs.update(run_id, status=RunStatus.RUNNING)
        try:
            async for chunk in self.graph.astream(graph_input, config, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        continue
                    retries = update.get("retry_count") if isinstance(update, dict) else None
                    await self.runs.update(run_id, stage=node, retry_count=retries)

            snapshot = await self.graph.aget_state(config)
            if snapshot.next:
                await self._pause(run_id, snapshot.tasks)
                return
            await self.runs.complete(run_id, snapshot.values["final_report"])
            log.info("run_completed", run_id=run_id)
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

    async def _pause(self, run_id: str, tasks: Any) -> None:
        interrupts = [i for task in tasks for i in task.interrupts]
        if not interrupts:
            raise InvalidStateError(f"run {run_id} stopped without finishing or asking for input")
        request = ApprovalRequest.model_validate(interrupts[0].value)
        approval = await self.approvals.create(request)
        await self.runs.update(run_id, status=RunStatus.AWAITING_APPROVAL, stage="human_approval")
        log.info("approval_requested", run_id=run_id, approval_id=approval.approval_id)
