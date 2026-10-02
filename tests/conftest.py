import asyncio
import os
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
from retrieval.backend import InMemoryBackend
from retrieval.embeddings import HashEmbedder
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import build_documents, ingest
from retrieval.models import SearchDocument
from storage.db import Database
from storage.incidents import IncidentRepository
from tools.backend import SimulatedOpsBackend


@pytest.fixture(autouse=True, scope="session")
def no_external_tracing() -> Iterator[None]:
    """Tests must never send traces anywhere, whatever the developer's shell has set."""
    names = (
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_TRACES_EXPORTER",
    )
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    os.environ["LANGSMITH_TRACING"] = "false"
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


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
        search_backend="memory",
        embedding_provider="hash",
        eval_reports_dir=tmp_path / "reports",
        langsmith_api_key=None,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="session")
def knowledge_docs(backend: SimulatedOpsBackend) -> list[SearchDocument]:
    return build_documents(ops=backend)


@pytest.fixture(scope="session")
def searcher(knowledge_docs: list[SearchDocument]) -> HybridSearcher:
    embedder = HashEmbedder()
    memory = InMemoryBackend()
    asyncio.run(ingest(memory, embedder, knowledge_docs))
    return HybridSearcher(memory, embedder)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
