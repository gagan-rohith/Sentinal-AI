from datetime import datetime
from statistics import median

from pydantic import BaseModel

from core.models import MetricSeries
from tools.backend import SimulatedOpsBackend
from tools.common import WindowQuery

ANOMALY_CHANGE_PCT = 50.0


class MetricSummary(BaseModel):
    name: str
    unit: str
    baseline: float
    latest: float
    peak: float
    change_pct: float | None
    anomalous: bool


class MetricsResult(BaseModel):
    service: str
    start: datetime
    end: datetime
    summaries: list[MetricSummary]
    series: list[MetricSeries]

    def anomalies(self) -> list[MetricSummary]:
        return [s for s in self.summaries if s.anomalous]


def summarize(series: MetricSeries) -> MetricSummary:
    values = [p.value for p in series.points]
    # The first third of the window is treated as the pre-incident baseline.
    baseline = median(values[: max(len(values) // 3, 1)])
    latest = values[-1]
    change: float | None = None
    if baseline:
        change = round((latest - baseline) / abs(baseline) * 100, 1)
        anomalous = abs(change) >= ANOMALY_CHANGE_PCT
    else:
        anomalous = latest > 0
    return MetricSummary(
        name=series.name,
        unit=series.unit,
        baseline=round(baseline, 2),
        latest=latest,
        peak=max(values),
        change_pct=change,
        anomalous=anomalous,
    )


async def get_service_metrics(backend: SimulatedOpsBackend, query: WindowQuery) -> MetricsResult:
    start, end = query.window(backend)
    series = backend.metrics(query.service, start, end)
    return MetricsResult(
        service=query.service,
        start=start,
        end=end,
        summaries=[summarize(s) for s in series],
        series=series,
    )
