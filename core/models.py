from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from core.enums import (
    ChangeType,
    DeploymentStatus,
    Environment,
    HealthStatus,
    IncidentStatus,
    LogLevel,
    Severity,
)

ServiceName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9-]{1,62}$")
]
IncidentId = Annotated[str, StringConstraints(pattern=r"^INC-[0-9]{4,}$")]


class RecentChange(BaseModel):
    change_id: str
    change_type: ChangeType
    description: str
    timestamp: datetime


class IncidentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10)
    service: ServiceName
    environment: Environment
    severity: Severity
    timestamp: AwareDatetime
    symptoms: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    recent_changes: list[RecentChange] = Field(default_factory=list)
    metrics_summary: dict[str, float] = Field(default_factory=dict)
    deployment_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class IncidentCreate(IncidentBase):
    # Ground truth fields are only set for the synthetic eval dataset.
    ground_truth_root_cause: str | None = None
    root_cause_category: str | None = None
    expected_remediation: str | None = None


class Incident(IncidentCreate):
    incident_id: IncidentId
    status: IncidentStatus = IncidentStatus.OPEN
    relevant_runbook_ids: list[str] = Field(
        default_factory=list,
        description="Runbooks an expert would consult. Used as retrieval ground truth.",
    )

    def search_text(self) -> str:
        # Deliberately excludes ground truth fields so they never leak into retrieval.
        parts = [self.title, self.description, *self.symptoms, *self.error_messages]
        parts += [change.description for change in self.recent_changes]
        return "\n".join(parts)


class LogEntry(BaseModel):
    timestamp: datetime
    service: str
    level: LogLevel
    message: str
    pod: str | None = None
    trace_id: str | None = None


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    service: str
    name: str
    unit: str
    points: list[MetricPoint]

    @property
    def latest(self) -> float | None:
        return self.points[-1].value if self.points else None

    @property
    def peak(self) -> float | None:
        return max((p.value for p in self.points), default=None)


class Deployment(BaseModel):
    deployment_id: str
    service: str
    version: str
    status: DeploymentStatus
    timestamp: datetime
    author: str
    change_summary: str


class ServiceHealth(BaseModel):
    service: str
    status: HealthStatus
    error_rate_pct: float | None
    p99_latency_ms: float | None
    observed_at: datetime | None
    reasons: list[str] = Field(default_factory=list)


class PodInfo(BaseModel):
    name: str
    namespace: str
    service: str
    status: str
    restarts: int
    age_minutes: int
