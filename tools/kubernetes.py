import hashlib

from pydantic import BaseModel, Field

from core.models import PodInfo, ServiceName
from data.catalog import SERVICES
from tools.backend import SimulatedOpsBackend
from tools.common import ActionResult, WindowQuery
from tools.metrics import get_service_metrics


class PodsQuery(BaseModel):
    namespace: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")


class PodsResult(BaseModel):
    namespace: str
    pods: list[PodInfo]


class RestartRequest(BaseModel):
    service: ServiceName


def _pod_name(service: str, index: int) -> str:
    digest = hashlib.sha1(f"{service}:{index}".encode()).hexdigest()
    return f"{service}-{digest[:9]}-{digest[-5:]}"


async def get_kubernetes_pods(backend: SimulatedOpsBackend, query: PodsQuery) -> PodsResult:
    pods: list[PodInfo] = []
    for profile in SERVICES.values():
        if profile.namespace != query.namespace:
            continue
        metrics = await get_service_metrics(backend, WindowQuery(service=profile.name, minutes=10))
        latest = {s.name: s.latest for s in metrics.summaries}
        restarts = int(latest.get("pod_restarts", 0))
        available = int(latest.get("available_replicas", profile.replicas))
        for i in range(profile.replicas):
            crashing = i >= available
            pods.append(
                PodInfo(
                    name=_pod_name(profile.name, i),
                    namespace=profile.namespace,
                    service=profile.name,
                    status="CrashLoopBackOff" if crashing else "Running",
                    restarts=restarts,
                    age_minutes=3 if crashing else 4320,
                )
            )
    return PodsResult(namespace=query.namespace, pods=pods)


async def restart_service(backend: SimulatedOpsBackend, request: RestartRequest) -> ActionResult:
    backend.require_service(request.service)
    profile = SERVICES[request.service]
    return ActionResult(
        action="restart_service",
        service=request.service,
        status="completed",
        message=(
            f"Rolling restart of {profile.replicas} pods in {profile.namespace}/{request.service} "
            "completed (simulated)."
        ),
        executed_at=backend.now(request.service),
        details={"namespace": profile.namespace, "replicas": profile.replicas},
    )
