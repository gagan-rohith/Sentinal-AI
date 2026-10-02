"""Structural checks on the deployment files. Schema validation runs in CI (kubeconform,
terraform validate); these catch project-specific mistakes in any environment."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.enums import RunStatus
from storage.db import Database
from storage.runs import RunRepository

ROOT = Path(__file__).resolve().parents[2]


def manifests() -> list[dict[str, Any]]:
    docs = []
    for path in sorted((ROOT / "k8s").glob("*.yaml")):
        docs += [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    return docs


def resource(kind: str, name: str) -> dict[str, Any]:
    [doc] = [d for d in manifests() if d["kind"] == kind and d["metadata"]["name"] == name]
    return doc


def container(deployment: str) -> dict[str, Any]:
    [only] = resource("Deployment", deployment)["spec"]["template"]["spec"]["containers"]
    return only


def test_every_resource_is_namespaced_and_labelled() -> None:
    for doc in manifests():
        if doc["kind"] == "Namespace":
            continue
        assert doc["metadata"]["namespace"] == "sentinel", doc["metadata"]["name"]
        assert doc["metadata"]["labels"]["app.kubernetes.io/part-of"] == "sentinel-ai"


def test_api_has_probes_limits_and_hardening() -> None:
    api = container("sentinel-api")
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert api[probe]["httpGet"]["path"] == "/health"
    assert set(api["resources"]) == {"requests", "limits"}
    assert api["securityContext"]["readOnlyRootFilesystem"] is True
    assert api["securityContext"]["allowPrivilegeEscalation"] is False
    mounts = {m["mountPath"] for m in api["volumeMounts"]}
    assert mounts == {"/data", "/tmp"}


def test_critic_is_hardened_and_stateless() -> None:
    critic = container("sentinel-critic")
    for probe in ("readinessProbe", "livenessProbe"):
        assert critic[probe]["httpGet"]["path"] == "/health"
    assert set(critic["resources"]) == {"requests", "limits"}
    assert critic["securityContext"]["readOnlyRootFilesystem"] is True
    assert {m["mountPath"] for m in critic["volumeMounts"]} == {"/tmp"}
    # Least privilege: the critic gets its own secret, never the API's keys.
    secrets = {s["secretRef"]["name"] for s in critic["envFrom"] if "secretRef" in s}
    assert secrets == {"sentinel-critic-secrets"}


def test_single_writer_deployment() -> None:
    deployment = resource("Deployment", "sentinel-api")
    # SQLite on a ReadWriteOnce volume: never two pods at once.
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"


def test_no_credentials_in_manifests() -> None:
    config = resource("ConfigMap", "sentinel-config")
    assert not any("KEY" in name for name in config["data"])
    api = resource("Secret", "sentinel-secrets")["stringData"]
    assert api["ANTHROPIC_API_KEY"] == ""
    assert "<sha256" in api["API_KEYS"]
    assert api["CRITIC_API_KEY"].startswith("<")
    critic = resource("Secret", "sentinel-critic-secrets")["stringData"]
    assert "<sha256" in critic["CRITIC_API_KEY_SHA256"]
    assert critic["ANTHROPIC_API_KEY"] == ""


def test_config_keys_are_real_settings() -> None:
    from critic_service.server import CriticSettings

    # CriticSettings extends the API's Settings, so this covers both services.
    config = resource("ConfigMap", "sentinel-config")
    known = {name.upper() for name in CriticSettings.model_fields}
    assert set(config["data"]) <= known


def test_compose_api_waits_for_the_index_job() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    assert api["depends_on"]["ingest"]["condition"] == "service_completed_successfully"
    assert api["environment"]["AUTO_INDEX"] == "false"
    assert compose["services"]["ingest"]["command"][-1] == "--if-stale"


def test_compose_api_reviews_plans_through_the_critic_service() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    assert api["environment"]["CRITIC_MODE"] == "a2a"
    assert api["environment"]["CRITIC_URL"] == "http://critic:8100"
    assert api["depends_on"]["critic"]["condition"] == "service_healthy"
    assert compose["services"]["critic"]["environment"]["CRITIC_PUBLIC_URL"] == "http://critic:8100"


def test_env_file_never_enters_an_image() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored


@pytest.fixture
async def runs() -> Any:
    db = Database(":memory:")
    await db.connect()
    yield RunRepository(db)
    await db.close()


async def test_restart_marks_in_flight_runs_failed(runs: RunRepository) -> None:
    queued = await runs.create("INC-1001", "tester")
    running = await runs.create("INC-1002", "tester")
    await runs.update(running.run_id, status=RunStatus.RUNNING)
    paused = await runs.create("INC-1003", "tester")
    await runs.update(paused.run_id, status=RunStatus.AWAITING_APPROVAL)

    assert await runs.fail_interrupted() == 2
    for run_id in (queued.run_id, running.run_id):
        run = await runs.get(run_id)
        assert run.status is RunStatus.FAILED
        assert run.error_code == "interrupted"
    # A paused run resumes from its checkpoint, so it is left alone.
    assert (await runs.get(paused.run_id)).status is RunStatus.AWAITING_APPROVAL
