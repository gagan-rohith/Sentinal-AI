from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.enums import Severity
from core.models import ServiceName


class TicketRequest(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    service: ServiceName
    severity: Severity
    description: str = Field(min_length=10, max_length=10000)
    incident_id: str | None = Field(default=None, pattern=r"^INC-[0-9]{4,}$")


class Ticket(TicketRequest):
    ticket_id: str
    created_at: datetime


class TicketStore:
    """In-memory stand-in for a ticketing system such as Jira or PagerDuty."""

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}

    async def create(self, request: TicketRequest) -> Ticket:
        ticket = Ticket(
            ticket_id=f"OPS-{len(self._tickets) + 1:04d}",
            created_at=datetime.now(UTC),
            **request.model_dump(),
        )
        self._tickets[ticket.ticket_id] = ticket
        return ticket
