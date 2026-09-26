from pydantic import AwareDatetime, BaseModel

from core.enums import HealthStatus
from core.models import ServiceHealth, ServiceName
from tools.backend import SimulatedOpsBackend
from tools.common import WindowQuery
from tools.metrics import get_service_metrics

DOWN_ERROR_RATE = 50.0
DEGRADED_ERROR_RATE = 2.0
DEGRADED_P99_MULTIPLIER = 3.0


class HealthQuery(BaseModel):
    service: ServiceName
    end_time: AwareDatetime | None = None


async def get_service_health(backend: SimulatedOpsBackend, query: HealthQuery) -> ServiceHealth:
    metrics = await get_service_metrics(
        backend, WindowQuery(service=query.service, minutes=30, end_time=query.end_time)
    )
    by_name = {s.name: s for s in metrics.summaries}
    error_rate = by_name.get("error_rate_pct")
    p99 = by_name.get("p99_latency_ms")

    status = HealthStatus.HEALTHY
    reasons: list[str] = [] if metrics.series else ["no telemetry in window"]
    if error_rate and error_rate.latest >= DOWN_ERROR_RATE:
        status = HealthStatus.DOWN
        reasons.append(f"error rate {error_rate.latest}%")
    elif error_rate and error_rate.latest >= DEGRADED_ERROR_RATE:
        status = HealthStatus.DEGRADED
        reasons.append(f"error rate {error_rate.latest}%")
    if p99 and p99.baseline and p99.latest >= p99.baseline * DEGRADED_P99_MULTIPLIER:
        if status is HealthStatus.HEALTHY:
            status = HealthStatus.DEGRADED
        reasons.append(f"p99 latency {p99.latest}ms vs baseline {p99.baseline}ms")
    for summary in metrics.anomalies():
        if summary.name not in {"error_rate_pct", "p99_latency_ms"}:
            reasons.append(f"{summary.name} changed {summary.change_pct}% to {summary.latest}")

    return ServiceHealth(
        service=query.service,
        status=status,
        error_rate_pct=error_rate.latest if error_rate else None,
        p99_latency_ms=p99.latest if p99 else None,
        observed_at=metrics.end,
        reasons=reasons,
    )
