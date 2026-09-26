import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, timedelta

from core.enums import IncidentStatus, Severity
from core.exceptions import DuplicateIncidentError, NotFoundError
from core.models import Incident, IncidentCreate
from storage.db import Database

DUPLICATE_WINDOW = timedelta(hours=1)


def fingerprint(service: str, environment: str, title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.lower()).strip()
    return hashlib.sha1(f"{service}|{environment}|{normalized}".encode()).hexdigest()


class IncidentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def count(self) -> int:
        async with self.db.conn.execute("SELECT COUNT(*) FROM incidents") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def seed(self, incidents: Iterable[Incident]) -> int:
        rows = [self._row(incident) for incident in incidents]
        await self.db.conn.executemany(
            "INSERT OR IGNORE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
        await self.db.conn.commit()
        return len(rows)

    async def get(self, incident_id: str) -> Incident:
        async with self.db.conn.execute(
            "SELECT body FROM incidents WHERE incident_id = ?", (incident_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"incident {incident_id} not found")
        return Incident.model_validate_json(row["body"])

    async def list_incidents(
        self,
        *,
        service: str | None = None,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Incident]:
        clauses, params = [], []
        for column, value in (("service", service), ("status", status), ("severity", severity)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(str(value))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT body FROM incidents {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        async with self.db.conn.execute(query, (*params, limit, offset)) as cursor:
            rows = await cursor.fetchall()
        return [Incident.model_validate_json(row["body"]) for row in rows]

    async def create(self, payload: IncidentCreate) -> Incident:
        await self._check_duplicate(payload)
        incident = Incident(incident_id=await self._next_id(), **payload.model_dump())
        await self.db.conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)", self._row(incident)
        )
        await self.db.conn.commit()
        return incident

    async def _check_duplicate(self, payload: IncidentCreate) -> None:
        fp = fingerprint(payload.service, payload.environment, payload.title)
        async with self.db.conn.execute(
            "SELECT body FROM incidents WHERE fingerprint = ? AND status != ?",
            (fp, IncidentStatus.RESOLVED.value),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            existing = Incident.model_validate_json(row["body"])
            if abs(existing.timestamp - payload.timestamp) <= DUPLICATE_WINDOW:
                raise DuplicateIncidentError(
                    f"an open incident with the same service and title already exists: "
                    f"{existing.incident_id}",
                    details={"existing_incident_id": existing.incident_id},
                )

    async def _next_id(self) -> str:
        async with self.db.conn.execute(
            "SELECT MAX(CAST(SUBSTR(incident_id, 5) AS INTEGER)) FROM incidents"
        ) as cursor:
            row = await cursor.fetchone()
        current = row[0] if row and row[0] is not None else 1000
        return f"INC-{int(current) + 1}"

    @staticmethod
    def _row(incident: Incident) -> tuple[str, ...]:
        return (
            incident.incident_id,
            fingerprint(incident.service, incident.environment, incident.title),
            incident.service,
            incident.status.value,
            incident.severity.value,
            incident.timestamp.astimezone(UTC).isoformat(),
            incident.model_dump_json(),
        )
