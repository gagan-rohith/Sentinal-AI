"""Simulated operations backend.

Stands in for Loki/Prometheus/Argo/Kubernetes. Telemetry comes from the synthetic
dataset and is queried by time window, so a query ending at an incident's timestamp
sees exactly what an on-call engineer would have seen at that moment.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from core.exceptions import NotFoundError
from core.models import Deployment, LogEntry, MetricSeries
from data import DATA_DIR
from data.catalog import SERVICES
from data.loader import load_deployments, load_logs, load_metrics


class SimulatedOpsBackend:
    def __init__(
        self,
        logs: list[LogEntry],
        metrics: list[MetricSeries],
        deployments: list[Deployment],
    ) -> None:
        self._logs: dict[str, list[LogEntry]] = defaultdict(list)
        for entry in sorted(logs, key=lambda e: e.timestamp):
            self._logs[entry.service].append(entry)
        self._log_times = {s: [e.timestamp for e in entries] for s, entries in self._logs.items()}

        self._metrics: dict[str, list[MetricSeries]] = defaultdict(list)
        for series in metrics:
            self._metrics[series.service].append(series)

        self._deployments: dict[str, list[Deployment]] = defaultdict(list)
        for dep in sorted(deployments, key=lambda d: d.timestamp):
            self._deployments[dep.service].append(dep)

    @classmethod
    def from_data_dir(cls, root: Path = DATA_DIR) -> "SimulatedOpsBackend":
        return cls(load_logs(root), load_metrics(root), load_deployments(root))

    def require_service(self, service: str) -> None:
        if service not in SERVICES:
            raise NotFoundError(f"unknown service '{service}'", details={"service": service})

    def now(self, service: str) -> datetime:
        """Latest observed timestamp for a service; the simulated 'current time'."""
        self.require_service(service)
        candidates = [e.timestamp for e in self._logs.get(service, [])[-1:]]
        candidates += [s.points[-1].timestamp for s in self._metrics.get(service, []) if s.points]
        return max(candidates, default=datetime.now(UTC))

    def logs(self, service: str, start: datetime, end: datetime) -> list[LogEntry]:
        self.require_service(service)
        times = self._log_times.get(service, [])
        lo, hi = bisect_left(times, start), bisect_right(times, end)
        return self._logs[service][lo:hi]

    def metrics(self, service: str, start: datetime, end: datetime) -> list[MetricSeries]:
        self.require_service(service)
        result = []
        for series in self._metrics.get(service, []):
            points = [p for p in series.points if start <= p.timestamp <= end]
            if points:
                result.append(series.model_copy(update={"points": points}))
        return result

    def deployments(self, service: str, until: datetime | None = None) -> list[Deployment]:
        self.require_service(service)
        history = self._deployments.get(service, [])
        if until is not None:
            history = [d for d in history if d.timestamp <= until]
        return history

    def find_deployment(self, service: str, deployment_id: str) -> Deployment:
        for dep in self.deployments(service):
            if dep.deployment_id == deployment_id:
                return dep
        raise NotFoundError(
            f"deployment {deployment_id} not found for {service}",
            details={"service": service, "deployment_id": deployment_id},
        )
