"""Terminal walkthrough of the INC-1060 demo incident.

Run with `make demo` or `python -m app.demo`. It drives the real HTTP API in-process
with throwaway operator and admin keys and a temporary database, so it never touches
var/sentinel.db or needs the keys from .env. Search follows .env (Elasticsearch by
default); pass --memory to use the in-memory backend instead.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from auth.api_keys import generate_key, hash_key

INCIDENT_ID = "INC-1060"
WIDTH = 88
POLL_S = 0.2
TIMEOUT_S = 120.0

Printer = Callable[[str], None]


class DemoError(Exception):
    pass


def _bold(text: str) -> str:
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        return f"\033[1m{text}\033[0m"
    return text


class Narrator:
    def __init__(self, out: Printer = print, pause: float = 0.0) -> None:
        self.out = out
        self.pause = pause
        self.step = 0

    def section(self, title: str) -> None:
        self.step += 1
        if self.pause:
            time.sleep(self.pause)
        self.out("")
        self.out(_bold(f"{self.step}. {title}"))
        self.out("-" * min(WIDTH, len(title) + 4))

    def line(self, text: str = "", indent: int = 0) -> None:
        if not text:
            self.out("")
            return
        pad = " " * indent
        wrapped = textwrap.wrap(
            text, WIDTH, initial_indent=pad, subsequent_indent=pad + "  ", break_on_hyphens=False
        )
        for part in wrapped or [pad]:
            self.out(part)


def demo_settings(workdir: Path, memory: bool, keys: dict[str, str]) -> Settings:
    base = Settings()
    update: dict[str, Any] = {
        "database_path": workdir / "demo.db",
        "api_keys": ",".join(f"{role}:{hash_key(key)}" for role, key in keys.items()),
        "eval_reports_dir": base.eval_reports_dir,
        "langsmith_api_key": None,
        "log_level": "ERROR",
    }
    if memory:
        update["search_backend"] = "memory"
    return base.model_copy(update=update)


def _error(response: Any) -> str:
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    if error:
        return f"{response.status_code} {error.get('code')}: {error.get('message')}"
    return f"{response.status_code}: {body.get('detail', body)}"


def _expect(response: Any, status: int) -> Any:
    if response.status_code != status:
        raise DemoError(f"expected HTTP {status}, got {_error(response)}")
    return response.json()


def _wait(client: TestClient, headers: dict[str, str], run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        run = _expect(client.get(f"/agents/status/{run_id}", headers=headers), 200)
        if run["status"] not in ("queued", "running"):
            if run["status"] == "failed":
                raise DemoError(f"run failed: {run['error_code']}: {run['error_message']}")
            return dict(run)
        time.sleep(POLL_S)
    raise DemoError(f"run {run_id} did not settle within {TIMEOUT_S:.0f}s")


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def run_demo(client: TestClient, keys: dict[str, str], n: Narrator) -> dict[str, Any]:
    operator = {"X-API-Key": keys["operator"]}
    admin = {"X-API-Key": keys["admin"]}

    health = _expect(client.get("/health"), 200)
    if health["checks"].get("search") != "ok":
        raise DemoError(
            "search is not available. Start Elasticsearch with "
            "`docker compose up -d elasticsearch`, or rerun with --memory."
        )

    n.section("The incident")
    incident = _expect(client.get(f"/incidents/{INCIDENT_ID}", headers=operator), 200)
    n.line(f"{incident['incident_id']} ({incident['severity']}): {incident['title']}")
    n.line(f"{incident['service']} in {incident['environment']}")
    n.line(incident["description"])
    for name, value in incident["metrics_summary"].items():
        n.line(f"{name}: {value}", indent=2)

    n.section("An operator starts the analysis")
    run = _expect(client.post(f"/agents/analyze/{INCIDENT_ID}", headers=operator), 202)
    run_id = run["run_id"]
    n.line(f"POST /agents/analyze/{INCIDENT_ID} -> run {run_id}")
    run = _wait(client, operator, run_id)
    n.line(f"status: {run['status']}, stopped at stage {run['stage']}")

    n.section("The run pauses for a human")
    approval = _expect(client.get(f"/agents/{run_id}/approval", headers=operator), 200)
    request = approval["request"]
    n.line(
        f"Root cause: {request['root_cause']} "
        f"(confidence {_percent(request['root_cause_confidence'])})"
    )
    n.line(f"Overall risk: {request['overall_risk']}")
    n.line("Proposed production changes:")
    for action in request["actions"]:
        args = ", ".join(f"{k}={v}" for k, v in action["arguments"].items())
        n.line(f"{action['tool']}({args})  [{action['risk']} risk]", indent=2)
        n.line(action["description"], indent=4)
    n.line(f"Rollback: {request['rollback_plan']}")
    n.line("Nothing has changed in production yet.")

    n.section("An operator tries to approve")
    denied = client.post(f"/agents/{run_id}/approve", headers=operator, json={"comment": "go"})
    if denied.status_code != 403:
        raise DemoError(f"operator approval should be refused, got {_error(denied)}")
    n.line(f"Refused: {_error(denied)}")
    n.line("Approving production changes needs the admin role.")

    n.section("An admin approves")
    comment = "Pool saturation matches the runbook; restart approved."
    _expect(client.post(f"/agents/{run_id}/approve", headers=admin, json={"comment": comment}), 202)
    n.line(f'Approved with comment: "{comment}"')
    run = _wait(client, admin, run_id)
    n.line(f"status: {run['status']}")
    again = client.post(f"/agents/{run_id}/approve", headers=admin, json={"comment": "again"})
    n.line(f"Approving a second time is refused: {_error(again)}")

    report = _expect(client.get(f"/agents/{run_id}/report", headers=operator), 200)
    narrate_report(report, n)
    return dict(report)


def narrate_report(report: dict[str, Any], n: Narrator) -> None:
    n.section("How the agents got there")
    for call in report["agent_calls"]:
        model = f" ({call['model']})" if call["model"] else ""
        n.line(f"{call['agent']:<14} {call['mode']}{model}, {call['latency_ms']:.0f} ms", indent=2)
    triage = report.get("triage")
    if triage:
        n.line()
        n.line("Triage:")
        n.line(triage["summary"])
        n.line(f"Subsystem: {triage['subsystem']}. Severity: {triage['assessed_severity']}.")
        for symptom in triage["key_symptoms"]:
            n.line(f"- {symptom}", indent=2)

    n.section("Evidence gathered")
    counts: dict[str, int] = {}
    for item in report["evidence"]:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    n.line(
        f"{len(report['evidence'])} items from {report['tool_call_count']} tool calls: "
        + ", ".join(f"{count} {kind}" for kind, count in counts.items())
    )
    for item in report["evidence"][:6]:
        n.line(f"{item['id']}  {item['summary']}", indent=2)
    if len(report["evidence"]) > 6:
        n.line(f"... and {len(report['evidence']) - 6} more", indent=2)

    n.section("Hypotheses considered")
    selected = report["selected_root_cause"]["title"]
    for h in sorted(report["hypotheses"], key=lambda h: -h["confidence"]):
        if h["title"] == selected:
            label = "SELECTED"
        elif h["confidence"] == 0 or len(h["evidence_against"]) > len(h["evidence_for"]):
            label = "ruled out"
        else:
            label = "considered"
        n.line(f"[{label}] {h['title']} ({_percent(h['confidence'])})")
        n.line(h["description"], indent=4)
        n.line(
            f"for: {', '.join(h['evidence_for']) or 'none'}; "
            f"against: {', '.join(h['evidence_against']) or 'none'}",
            indent=4,
        )

    n.section("Remediation plan")
    plan = report["remediation_plan"]
    n.line(plan["summary"])
    for i, step in enumerate(plan["steps"], 1):
        action = f"  -> {step['action']['tool']}" if step["action"] else ""
        n.line(f"{i}. [{step['kind']}] {step['description']}{action}", indent=2)

    n.section("What was executed")
    approval = report.get("approval")
    if approval:
        n.line(f"Approved by {approval['decided_by']}")
    for action in report["executed_actions"]:
        n.line(f"{action['tool']}: {action['status']}. {action['message']}", indent=2)
    if not report["executed_actions"]:
        n.line("Nothing was executed.", indent=2)

    n.section("Postmortem")
    postmortem = report["postmortem"]
    n.line(postmortem["summary"])
    n.line(postmortem["impact"])
    n.line("Timeline:")
    for event in report["timeline"]:
        n.line(f"{event['timestamp'][:16].replace('T', ' ')}  {event['description']}", indent=2)
    if postmortem["prevention"]:
        n.line("Prevention:")
        for item in postmortem["prevention"]:
            n.line(f"- {item}", indent=2)
    critic = report.get("critic_review")
    if critic:
        n.line(f"Critic verdict: {critic['verdict']} after {report['retries']} retries.")
    n.line(f"Agents ran in {report['mode']} mode. Trace id {report['trace_id']}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--memory", action="store_true", help="use the in-memory search backend")
    parser.add_argument(
        "--pause", type=float, default=0.0, help="seconds to wait between sections, for recording"
    )
    args = parser.parse_args(argv)

    for name in ("HF_HUB_VERBOSITY", "TRANSFORMERS_VERBOSITY"):
        os.environ.setdefault(name, "error")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    keys = {"operator": generate_key(), "admin": generate_key()}
    n = Narrator(pause=args.pause)
    with tempfile.TemporaryDirectory(prefix="sentinel-demo-") as tmp:
        settings = demo_settings(Path(tmp), args.memory, keys)
        embedder = "hash" if settings.embedding_provider == "hash" else settings.embedding_model
        n.line(f"SentinelAI demo: search on {settings.search_backend}, embedder {embedder}")
        try:
            with TestClient(create_app(settings)) as client:
                run_demo(client, keys, n)
        except DemoError as exc:
            print(f"\ndemo failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
