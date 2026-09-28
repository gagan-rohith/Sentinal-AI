import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from agents.schemas import ApprovalDecision, ApprovalRequest
from auth.permissions import Principal
from core.enums import ApprovalStatus
from core.exceptions import InvalidStateError, NotFoundError
from storage.db import Database


class ApprovalRecord(BaseModel):
    approval_id: str
    run_id: str
    status: ApprovalStatus
    request: ApprovalRequest
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    comment: str | None
    consumed: list[str]


def action_key(tool: str, arguments: Mapping[str, Any]) -> str:
    return f"{tool}:{json.dumps(dict(arguments), sort_keys=True)}"


class ApprovalStore:
    """Persisted approvals. Also the tool registry's approval verifier."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, request: ApprovalRequest) -> ApprovalRecord:
        approval_id = f"apr-{request.run_id.removeprefix('run-')}"
        await self.db.conn.execute(
            "INSERT INTO approvals (approval_id, run_id, status, request, requested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                approval_id,
                request.run_id,
                ApprovalStatus.PENDING,
                request.model_dump_json(),
                datetime.now(UTC).isoformat(),
            ),
        )
        await self.db.conn.commit()
        return await self.get(approval_id)

    async def get(self, approval_id: str) -> ApprovalRecord:
        return await self._fetch("approval_id", approval_id)

    async def for_run(self, run_id: str) -> ApprovalRecord:
        return await self._fetch("run_id", run_id)

    async def _fetch(self, column: str, value: str) -> ApprovalRecord:
        async with self.db.conn.execute(
            f"SELECT * FROM approvals WHERE {column} = ?", (value,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"no approval found for {value}")
        data = dict(row)
        data["request"] = ApprovalRequest.model_validate_json(data["request"])
        data["consumed"] = json.loads(data["consumed"])
        return ApprovalRecord.model_validate(data)

    async def decide(
        self, run_id: str, *, approved: bool, principal: Principal, comment: str | None
    ) -> ApprovalDecision:
        decided_at = datetime.now(UTC)
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        # Conditional update: of two concurrent decisions, exactly one succeeds.
        cursor = await self.db.conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, decided_role = ?, "
            "comment = ? WHERE run_id = ? AND status = ?",
            (
                status,
                decided_at.isoformat(),
                principal.subject,
                principal.role,
                comment,
                run_id,
                ApprovalStatus.PENDING,
            ),
        )
        await self.db.conn.commit()
        if cursor.rowcount != 1:
            record = await self.for_run(run_id)
            raise InvalidStateError(
                f"approval {record.approval_id} was already {record.status}",
                details={"approval_id": record.approval_id, "status": record.status.value},
            )
        record = await self.for_run(run_id)
        return ApprovalDecision(
            approval_id=record.approval_id,
            approved=approved,
            decided_by=principal.subject,
            role=principal.role,
            comment=comment,
            decided_at=decided_at,
        )

    async def verify(self, approval_id: str, tool: str, arguments: Mapping[str, Any]) -> bool:
        """Consume one approved action. Each approved action can run exactly once."""
        try:
            record = await self.get(approval_id)
        except NotFoundError:
            return False
        key = action_key(tool, arguments)
        approved_keys = {action_key(a.tool, a.arguments) for a in record.request.actions}
        if (
            record.status is not ApprovalStatus.APPROVED
            or key not in approved_keys
            or key in record.consumed
        ):
            return False
        cursor = await self.db.conn.execute(
            "UPDATE approvals SET consumed = ? WHERE approval_id = ? AND consumed = ?",
            (json.dumps([*record.consumed, key]), approval_id, json.dumps(record.consumed)),
        )
        await self.db.conn.commit()
        return cursor.rowcount == 1
