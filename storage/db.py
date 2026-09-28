from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    service TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_incidents_fingerprint ON incidents (fingerprint);
CREATE INDEX IF NOT EXISTS ix_incidents_service ON incidents (service);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    requested_by TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    report TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_incident ON runs (incident_id);
"""


class Database:
    """Single shared aiosqlite connection. SQLite serializes writes, which is fine at demo scale."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def ping(self) -> bool:
        async with self.conn.execute("SELECT 1") as cursor:
            return await cursor.fetchone() is not None
