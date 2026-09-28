import uuid
from datetime import UTC, datetime

from pydantic import BaseModel

from agents.schemas import FinalReport
from core.enums import RunStatus
from core.exceptions import InvalidStateError, NotFoundError
from storage.db import Database

ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


class RunRecord(BaseModel):
    run_id: str
    incident_id: str
    status: RunStatus
    stage: str | None
    retry_count: int
    requested_by: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, incident_id: str, requested_by: str) -> RunRecord:
        async with self.db.conn.execute(
            "SELECT run_id FROM runs WHERE incident_id = ? AND status IN (?, ?)",
            (incident_id, *ACTIVE),
        ) as cursor:
            active = await cursor.fetchone()
        if active is not None:
            raise InvalidStateError(
                f"incident {incident_id} already has an analysis in progress",
                details={"run_id": active["run_id"]},
            )
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = _now()
        await self.db.conn.execute(
            "INSERT INTO runs (run_id, incident_id, status, retry_count, requested_by, "
            "created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
            (run_id, incident_id, RunStatus.QUEUED, requested_by, now, now),
        )
        await self.db.conn.commit()
        return await self.get(run_id)

    async def recent(self, limit: int = 20) -> list[RunRecord]:
        async with self.db.conn.execute(
            "SELECT run_id, incident_id, status, stage, retry_count, requested_by, error_code, "
            "error_message, created_at, updated_at FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [RunRecord.model_validate(dict(row)) for row in rows]

    async def get(self, run_id: str) -> RunRecord:
        async with self.db.conn.execute(
            "SELECT run_id, incident_id, status, stage, retry_count, requested_by, error_code, "
            "error_message, created_at, updated_at FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id} not found")
        return RunRecord.model_validate(dict(row))

    async def update(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: str | None = None,
        retry_count: int | None = None,
    ) -> None:
        await self.db.conn.execute(
            "UPDATE runs SET status = COALESCE(?, status), stage = COALESCE(?, stage), "
            "retry_count = COALESCE(?, retry_count), updated_at = ? WHERE run_id = ?",
            (status, stage, retry_count, _now(), run_id),
        )
        await self.db.conn.commit()

    async def complete(self, run_id: str, report: FinalReport) -> None:
        await self.db.conn.execute(
            "UPDATE runs SET status = ?, stage = 'done', report = ?, updated_at = ? "
            "WHERE run_id = ?",
            (RunStatus.COMPLETED, report.model_dump_json(), _now(), run_id),
        )
        await self.db.conn.commit()

    async def fail(self, run_id: str, code: str, message: str) -> None:
        await self.db.conn.execute(
            "UPDATE runs SET status = ?, error_code = ?, error_message = ?, updated_at = ? "
            "WHERE run_id = ?",
            (RunStatus.FAILED, code, message, _now(), run_id),
        )
        await self.db.conn.commit()

    async def fail_interrupted(self) -> int:
        """Mark runs left queued or running by a previous process as failed.

        Called at startup. Runs awaiting approval are untouched: they live in the
        checkpointer and resume normally. Assumes one API process per database, which
        SQLite requires anyway.
        """
        cursor = await self.db.conn.execute(
            "UPDATE runs SET status = ?, error_code = 'interrupted', error_message = ?, "
            "updated_at = ? WHERE status IN (?, ?)",
            (
                RunStatus.FAILED,
                "the service restarted while this run was in progress; start a new analysis",
                _now(),
                *ACTIVE,
            ),
        )
        await self.db.conn.commit()
        return cursor.rowcount

    async def report(self, run_id: str) -> FinalReport:
        run = await self.get(run_id)
        if run.status is not RunStatus.COMPLETED:
            raise InvalidStateError(
                f"run {run_id} is {run.status}; the report is available once it completes",
                details={"status": run.status.value},
            )
        async with self.db.conn.execute(
            "SELECT report FROM runs WHERE run_id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or row["report"] is None:
            raise NotFoundError(f"report for run {run_id} not found")
        return FinalReport.model_validate_json(row["report"])
