import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.record_demo import ADMIN, COMMENT, Recorder, record_all, stage_sequence
from core.enums import Role
from tests.conftest import DEMO_INCIDENT_ID, KEYS

RECORDER_KEYS = {"operator": KEYS[Role.OPERATOR], "admin": KEYS[Role.ADMIN]}


def test_paused_run_is_recorded_both_ways(client: TestClient) -> None:
    recording = Recorder(client, RECORDER_KEYS).record(DEMO_INCIDENT_ID)

    assert recording["approval"]["request"]["actions"][0]["tool"] == "restart_service"
    assert recording["stages_approved"][-3:] == ["human_approval", "action_execution", "postmortem"]
    assert recording["stages_rejected"][-2:] == ["human_approval", "postmortem"]
    approved, rejected = recording["report_approved"], recording["report_rejected"]
    assert approved["executed_actions"][0]["status"] == "succeeded"
    assert rejected["executed_actions"] == []
    assert approved["approval"]["decided_by"] == ADMIN
    assert approved["approval"]["comment"] == COMMENT
    assert "apikey:" not in json.dumps(recording)


def test_stage_sequence_follows_agent_calls() -> None:
    calls = ["triage", "retrieval", "root_cause", "remediation", "critic", "root_cause"]
    calls += ["remediation", "critic", "postmortem"]
    report = {"agent_calls": [{"agent": a} for a in calls]}
    assert stage_sequence(report, None) == [
        "triage",
        "context_collection",
        "retrieval",
        "root_cause",
        "remediation",
        "critic",
        "root_cause",
        "remediation",
        "critic",
        "postmortem",
    ]


def test_record_all_writes_every_incident(client: TestClient, tmp_path: Path) -> None:
    manifest = record_all(client, RECORDER_KEYS, tmp_path / "demo")

    incidents = json.loads((tmp_path / "demo" / "incidents.json").read_text())
    runs = list((tmp_path / "demo" / "runs").glob("*.json"))
    assert manifest["incidents"] == len(incidents) == len(runs)
    assert DEMO_INCIDENT_ID in manifest["needs_approval"]
