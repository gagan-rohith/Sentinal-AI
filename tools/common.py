from datetime import datetime, timedelta
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from core.models import ServiceName
from tools.backend import SimulatedOpsBackend


class WindowQuery(BaseModel):
    service: ServiceName
    minutes: int = Field(default=30, ge=1, le=1440)
    end_time: AwareDatetime | None = Field(
        default=None, description="End of the query window. Defaults to the latest data point."
    )

    def window(self, backend: SimulatedOpsBackend) -> tuple[datetime, datetime]:
        end = self.end_time or backend.now(self.service)
        return end - timedelta(minutes=self.minutes), end


class ActionResult(BaseModel):
    action: str
    service: str
    status: str
    message: str
    executed_at: datetime
    simulated: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
