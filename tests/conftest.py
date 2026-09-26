from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from auth.api_keys import hash_key
from core.enums import Role
from core.models import Incident
from data.loader import load_incidents
from storage.db import Database
from storage.incidents import IncidentRepository
from tools.backend import SimulatedOpsBackend

KEYS = {
    Role.VIEWER: "test-viewer-key",
    Role.OPERATOR: "test-operator-key",
    Role.ADMIN: "test-admin-key",
}
DEMO_INCIDENT_ID = "INC-1060"


def headers(role: Role) -> dict[str, str]:
    return {"X-API-Key": KEYS[role]}


@pytest.fixture(scope="session")
def incidents() -> list[Incident]:
    return load_incidents()


@pytest.fixture(scope="session")
def demo_incident(incidents: list[Incident]) -> Incident:
    return next(i for i in incidents if i.incident_id == DEMO_INCIDENT_ID)


@pytest.fixture(scope="session")
def backend() -> SimulatedOpsBackend:
    return SimulatedOpsBackend.from_data_dir()


@pytest.fixture
async def repo() -> AsyncIterator[IncidentRepository]:
    db = Database(":memory:")
    await db.connect()
    yield IncidentRepository(db)
    await db.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        api_keys=",".join(f"{role.value}:{hash_key(key)}" for role, key in KEYS.items()),
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
