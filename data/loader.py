import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from core.models import Deployment, Incident, LogEntry, MetricPoint, MetricSeries
from data import DATA_DIR


class Runbook(BaseModel):
    runbook_id: str
    title: str
    tags: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    body: str


class ServiceDoc(BaseModel):
    service: str
    team: str
    namespace: str
    tags: list[str] = Field(default_factory=list)
    body: str


def _split_front_matter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} is missing front matter")
    _, header, body = text.split("---", 2)
    meta = yaml.safe_load(header)
    if not isinstance(meta, dict):
        raise ValueError(f"{path} has invalid front matter")
    return meta, body.strip()


def load_runbooks(root: Path = DATA_DIR) -> list[Runbook]:
    runbooks = []
    for path in sorted((root / "runbooks").glob("*.md")):
        meta, body = _split_front_matter(path)
        runbooks.append(Runbook(**meta, body=body))
    return runbooks


def load_service_docs(root: Path = DATA_DIR) -> list[ServiceDoc]:
    docs = []
    for path in sorted((root / "services").glob("*.md")):
        meta, body = _split_front_matter(path)
        docs.append(ServiceDoc(**meta, body=body))
    return docs


def load_incidents(root: Path = DATA_DIR) -> list[Incident]:
    raw = json.loads((root / "incidents" / "incidents.json").read_text(encoding="utf-8"))
    return [Incident.model_validate(item) for item in raw]


def load_logs(root: Path = DATA_DIR) -> list[LogEntry]:
    with (root / "telemetry" / "logs.jsonl").open(encoding="utf-8") as fh:
        return [LogEntry.model_validate_json(line) for line in fh if line.strip()]


def load_metrics(root: Path = DATA_DIR) -> list[MetricSeries]:
    series = []
    with (root / "telemetry" / "metrics.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            start = datetime.fromisoformat(record["start"])
            step = timedelta(seconds=record["step_seconds"])
            points = [
                MetricPoint(timestamp=start + step * i, value=value)
                for i, value in enumerate(record["values"])
            ]
            series.append(
                MetricSeries(
                    service=record["service"],
                    name=record["name"],
                    unit=record["unit"],
                    points=points,
                )
            )
    return series


def load_deployments(root: Path = DATA_DIR) -> list[Deployment]:
    raw = json.loads((root / "telemetry" / "deployments.json").read_text(encoding="utf-8"))
    return [Deployment.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def default_incidents() -> tuple[Incident, ...]:
    return tuple(load_incidents())
