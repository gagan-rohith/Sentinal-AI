from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceKind(StrEnum):
    HEALTH = "health"
    LOG = "log"
    METRIC = "metric"
    DEPLOYMENT = "deployment"
    CHANGE = "change"
    RUNBOOK = "runbook"
    INCIDENT = "incident"
    SERVICE_DOC = "service_doc"


class Evidence(BaseModel):
    id: str
    kind: EvidenceKind
    summary: str
    # Stable reference to where the evidence came from, used to avoid duplicates.
    source: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def add_evidence(
    catalog: list[Evidence],
    kind: EvidenceKind,
    summary: str,
    source: str,
    timestamp: datetime | None = None,
    **metadata: Any,
) -> tuple[list[Evidence], Evidence]:
    """Return a new catalog with the item appended, or the existing item for the same source."""
    for item in catalog:
        if item.source == source:
            return catalog, item
    item = Evidence(
        id=f"E{len(catalog) + 1}",
        kind=kind,
        summary=summary,
        source=source,
        timestamp=timestamp,
        metadata=metadata,
    )
    return [*catalog, item], item


def evidence_ids(catalog: Iterable[Evidence]) -> set[str]:
    return {item.id for item in catalog}


def render(catalog: Iterable[Evidence]) -> str:
    """Compact text form used in prompts: one line per item, id first."""
    lines = []
    for item in catalog:
        when = f" @ {item.timestamp.isoformat()}" if item.timestamp else ""
        lines.append(f"[{item.id}] ({item.kind}{when}) {item.summary}")
    return "\n".join(lines) if lines else "(no evidence collected)"
