"""Generate synthetic incidents and the telemetry behind them.

Usage: python -m data.generate_data [--seed 42]

Every incident sits on its own day, so a time-window query for a service only ever
sees the telemetry of one incident. The last incident (the checkout-api demo) is the
most recent one and is left open; the rest are resolved history.
"""

import argparse
import json
import random
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.enums import (
    ChangeType,
    DeploymentStatus,
    Environment,
    IncidentStatus,
    LogLevel,
)
from core.models import Deployment, Incident, LogEntry, RecentChange
from data import DATA_DIR
from data.catalog import SERVICES
from data.scenarios import SCENARIOS, Scenario

BASE_TIME = datetime(2026, 3, 2, tzinfo=UTC)
WINDOW_BEFORE = timedelta(minutes=40)
WINDOW_AFTER = timedelta(minutes=5)
RAMP_MINUTES = 10
ENVIRONMENTS = (Environment.PRODUCTION, Environment.PRODUCTION, Environment.STAGING)
DEMO_CATEGORY = "postgres_pool_exhaustion"

BASE_METRICS = {
    "error_rate_pct": "%",
    "p99_latency_ms": "ms",
    "cpu_pct": "%",
    "memory_pct": "%",
    "requests_per_sec": "req/s",
}

ROUTINE_LOGS = (
    "GET /api/v1/{resource} 200 duration={ms}ms",
    "POST /api/v1/{resource} 201 duration={ms}ms",
    "health check passed",
    "processed batch of {n} records",
)
NOISE_LOGS = (
    "retrying request to {dep} (attempt 1 of 3)",
    "slow request GET /api/v1/{resource} duration={slow}ms",
)
RESOURCES = ("orders", "items", "users", "sessions", "products", "quotes")


@dataclass
class MetricRecord:
    service: str
    name: str
    unit: str
    start: datetime
    step_seconds: int
    values: list[float]


@dataclass
class Dataset:
    incidents: list[Incident] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    metrics: list[MetricRecord] = field(default_factory=list)
    deployments: list[Deployment] = field(default_factory=list)


def _fill(template: str, service: str, pod: str = "") -> str:
    return template.replace("{service}", service).replace("{pod}", pod)


def _pod_names(rng: random.Random, service: str, count: int) -> list[str]:
    alphabet = string.ascii_lowercase + string.digits
    replicaset = "".join(rng.choices(alphabet, k=9))
    return [f"{service}-{replicaset}-{''.join(rng.choices(alphabet, k=5))}" for _ in range(count)]


class Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.data = Dataset()
        self._versions: dict[str, int] = {}
        self._deploy_seq = 0

    def _next_deployment(
        self, service: str, at: datetime, summary: str, author: str = "ci-bot"
    ) -> Deployment:
        minor = self._versions.get(service, 10) + 1
        self._versions[service] = minor
        self._deploy_seq += 1
        deployment = Deployment(
            deployment_id=f"dep-{self._deploy_seq:05d}",
            service=service,
            version=f"v2.{minor}.0",
            status=DeploymentStatus.SUCCEEDED,
            timestamp=at,
            author=author,
            change_summary=summary,
        )
        self.data.deployments.append(deployment)
        return deployment

    def build(self) -> Dataset:
        plan: list[tuple[Scenario, int]] = [
            (scenario, variant) for scenario in SCENARIOS for variant in range(3)
        ]
        demo = next(p for p in plan if p[0].category == DEMO_CATEGORY and p[1] == 0)
        plan.remove(demo)
        plan.append(demo)

        timestamps = [
            BASE_TIME
            + timedelta(days=day, hours=self.rng.randint(1, 20), minutes=self.rng.randint(0, 59))
            for day in range(len(plan))
        ]
        # Routine deploys are created interleaved with incidents so versions and ids stay
        # in chronological order per service.
        pending = self._routine_deployments(plan, timestamps)

        for number, ((scenario, variant), ts) in enumerate(zip(plan, timestamps, strict=True)):
            while pending and pending[0][1] < ts:
                service, at, summary = pending.pop(0)
                self._next_deployment(service, at, summary)
            is_demo = (scenario, variant) == demo
            self._incident(1001 + number, scenario, variant, ts, open_incident=is_demo)
        for service, at, summary in pending:
            self._next_deployment(service, at, summary)

        self.data.deployments.sort(key=lambda d: (d.service, d.timestamp))
        return self.data

    def _routine_deployments(
        self, plan: list[tuple[Scenario, int]], timestamps: list[datetime]
    ) -> list[tuple[str, datetime, str]]:
        incident_days: dict[str, set[int]] = {}
        for (scenario, variant), ts in zip(plan, timestamps, strict=True):
            day = (ts - BASE_TIME).days
            incident_days.setdefault(scenario.services[variant], set()).update(
                {day - 1, day, day + 1}
            )
        summaries = (
            "Dependency updates",
            "Improve request logging",
            "Minor bug fixes",
            "Refactor internal client",
        )
        routine: list[tuple[str, datetime, str]] = []
        for service in SERVICES:
            for day in range(0, len(plan), 4):
                if day in incident_days.get(service, set()):
                    continue
                at = BASE_TIME + timedelta(days=day, hours=9, minutes=self.rng.randint(0, 50))
                routine.append((service, at, self.rng.choice(summaries)))
        return sorted(routine, key=lambda r: r[1])

    def _incident(
        self, number: int, scenario: Scenario, variant: int, ts: datetime, *, open_incident: bool
    ) -> None:
        rng = self.rng
        service = scenario.services[variant]
        profile = SERVICES[service]
        pods = _pod_names(rng, service, min(profile.replicas, 4))
        scale = rng.uniform(0.85, 1.15)

        recent_changes: list[RecentChange] = []
        deployment_id: str | None = None

        if scenario.distractor_deploy:
            dep = self._next_deployment(
                service, ts - timedelta(hours=3), scenario.distractor_deploy
            )
            recent_changes.append(
                RecentChange(
                    change_id=dep.deployment_id,
                    change_type=ChangeType.DEPLOYMENT,
                    description=f"{dep.version}: {dep.change_summary}",
                    timestamp=dep.timestamp,
                )
            )
            deployment_id = dep.deployment_id

        change_at = ts - timedelta(minutes=scenario.change_offset_min)
        if scenario.change:
            change_type, text = scenario.change
            text = _fill(text, service)
            if change_type is ChangeType.DEPLOYMENT:
                dep = self._next_deployment(service, change_at, text, author="release-pipeline")
                change_id = dep.deployment_id
                deployment_id = dep.deployment_id
                text = f"{dep.version}: {text}"
            else:
                change_id = f"chg-{number}"
            recent_changes.append(
                RecentChange(
                    change_id=change_id,
                    change_type=change_type,
                    description=text,
                    timestamp=change_at,
                )
            )

        onset_min = min(15, max(scenario.change_offset_min - 2, 3))
        onset = ts - timedelta(minutes=onset_min)
        start = ts - WINDOW_BEFORE

        summary = self._metrics(scenario, service, start, onset, ts, scale)
        self._logs(scenario, service, pods, start, onset, ts, recent_changes)

        tags = [*scenario.tags, service, ENVIRONMENTS[variant].value]
        self.data.incidents.append(
            Incident(
                incident_id=f"INC-{number}",
                title=_fill(scenario.title, service),
                description=_fill(scenario.description, service),
                service=service,
                environment=ENVIRONMENTS[variant],
                severity=scenario.severities[variant],
                status=IncidentStatus.OPEN if open_incident else IncidentStatus.RESOLVED,
                timestamp=ts,
                symptoms=list(scenario.symptoms),
                error_messages=[_fill(m, service) for m in scenario.error_messages],
                recent_changes=recent_changes,
                metrics_summary=summary,
                deployment_id=deployment_id,
                ground_truth_root_cause=_fill(scenario.root_cause, service),
                root_cause_category=scenario.category,
                expected_remediation=_fill(scenario.remediation, service),
                relevant_runbook_ids=list(scenario.runbook_ids),
                tags=tags,
            )
        )

    def _metrics(
        self,
        scenario: Scenario,
        service: str,
        start: datetime,
        onset: datetime,
        ts: datetime,
        scale: float,
    ) -> dict[str, float]:
        profile = SERVICES[service]
        baselines = {
            "error_rate_pct": 0.3,
            "p99_latency_ms": profile.baseline_p99_ms,
            "cpu_pct": profile.baseline_cpu_pct,
            "memory_pct": profile.baseline_memory_pct,
            "requests_per_sec": profile.baseline_rps,
        }
        # name -> (baseline, peak, unit, ceiling)
        series: dict[str, tuple[float, float, str, float | None]] = {
            name: (value, value, BASE_METRICS[name], None) for name, value in baselines.items()
        }
        for name, anomaly in scenario.anomalies.items():
            if anomaly.hard_limit:
                ceiling: float | None = max(anomaly.baseline, anomaly.peak)
                peak = anomaly.peak
            else:
                ceiling = None
                peak = anomaly.baseline + (anomaly.peak - anomaly.baseline) * scale
            series[name] = (anomaly.baseline, peak, anomaly.unit, ceiling)

        steps = int((WINDOW_BEFORE + WINDOW_AFTER).total_seconds() // 60) + 1
        summary: dict[str, float] = {}
        for name, (baseline, peak, unit, ceiling) in series.items():
            values: list[float] = []
            for i in range(steps):
                at = start + timedelta(minutes=i)
                progress = (at - onset).total_seconds() / 60 / RAMP_MINUTES
                target = baseline + (peak - baseline) * min(max(progress, 0.0), 1.0)
                value = target * self.rng.uniform(0.96, 1.04)
                if unit == "%":
                    value = min(value, 100.0)
                if ceiling is not None:
                    value = min(value, ceiling)
                values.append(round(max(value, 0.0), 2))
            self.data.metrics.append(MetricRecord(service, name, unit, start, 60, values))
            if name in scenario.anomalies:
                summary[name] = values[int(WINDOW_BEFORE.total_seconds() // 60)]
        return summary

    def _logs(
        self,
        scenario: Scenario,
        service: str,
        pods: list[str],
        start: datetime,
        onset: datetime,
        ts: datetime,
        recent_changes: list[RecentChange],
    ) -> None:
        rng = self.rng
        deps = SERVICES[service].dependencies
        end = ts + WINDOW_AFTER
        entries: list[LogEntry] = []

        def emit(at: datetime, level: LogLevel, message: str) -> None:
            entries.append(
                LogEntry(
                    timestamp=at,
                    service=service,
                    level=level,
                    message=message,
                    pod=rng.choice(pods),
                    trace_id=f"{rng.getrandbits(64):016x}",
                )
            )

        at = start
        while at < end:
            template = rng.choice(ROUTINE_LOGS)
            emit(
                at,
                LogLevel.INFO,
                template.format(
                    resource=rng.choice(RESOURCES), ms=rng.randint(12, 180), n=rng.randint(50, 500)
                ),
            )
            if rng.random() < 0.08:
                emit(
                    at + timedelta(seconds=7),
                    LogLevel.WARN,
                    rng.choice(NOISE_LOGS).format(
                        dep=rng.choice(deps),
                        resource=rng.choice(RESOURCES),
                        slow=rng.randint(900, 1500),
                    ),
                )
            at += timedelta(seconds=rng.randint(40, 110))

        for change in recent_changes:
            if start <= change.timestamp < end:
                emit(change.timestamp, LogLevel.INFO, f"change applied: {change.description}")

        at = onset
        while at < end:
            progress = min((at - onset).total_seconds() / 60 / RAMP_MINUTES, 1.0)
            if rng.random() < 0.25 + 0.7 * progress:
                pod = rng.choice(pods)
                message = _fill(rng.choice(scenario.log_errors), service, pod)
                level = LogLevel.ERROR
                if message.startswith("DEBUG "):
                    level, message = LogLevel.DEBUG, message.removeprefix("DEBUG ")
                elif message.startswith(("panic:", "FATAL:")):
                    level = LogLevel.FATAL
                emit(at, level, message)
            at += timedelta(seconds=rng.randint(10, 35))

        entries.sort(key=lambda e: e.timestamp)
        self.data.logs.extend(entries)


def write_dataset(dataset: Dataset, root: Path) -> None:
    incidents_dir = root / "incidents"
    telemetry_dir = root / "telemetry"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    (incidents_dir / "incidents.json").write_text(
        json.dumps([i.model_dump(mode="json") for i in dataset.incidents], indent=2) + "\n",
        encoding="utf-8",
    )
    with (telemetry_dir / "logs.jsonl").open("w", encoding="utf-8") as fh:
        for entry in dataset.logs:
            fh.write(entry.model_dump_json() + "\n")
    with (telemetry_dir / "metrics.jsonl").open("w", encoding="utf-8") as fh:
        for m in dataset.metrics:
            record = {
                "service": m.service,
                "name": m.name,
                "unit": m.unit,
                "start": m.start.isoformat(),
                "step_seconds": m.step_seconds,
                "values": m.values,
            }
            fh.write(json.dumps(record) + "\n")
    (telemetry_dir / "deployments.json").write_text(
        json.dumps([d.model_dump(mode="json") for d in dataset.deployments], indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    dataset = Generator(args.seed).build()
    write_dataset(dataset, args.out)
    print(
        f"wrote {len(dataset.incidents)} incidents, {len(dataset.logs)} log lines, "
        f"{len(dataset.metrics)} metric series, {len(dataset.deployments)} deployments "
        f"to {args.out}"
    )


if __name__ == "__main__":
    main()
