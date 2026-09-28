"""Input types and tool annotations for the MCP tools.

Clients see these as the JSON schema of each tool. Output types are the same Pydantic
models the tool registry returns, so responses are structured and validated.
"""

from datetime import datetime
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)

Service = Annotated[str, Field(description="Service name, for example checkout-api")]
EndTime = Annotated[
    datetime | None,
    Field(description="End of the window, ISO 8601 with timezone. Defaults to the latest data."),
]
Minutes = Annotated[int, Field(ge=1, le=1440, description="Window length in minutes")]
LogLimit = Annotated[int, Field(ge=1, le=500)]
Query = Annotated[str, Field(min_length=3, max_length=1000)]
TopK = Annotated[int, Field(ge=1, le=20)]
Title = Annotated[str, Field(min_length=5, max_length=200)]
Description = Annotated[str, Field(min_length=10, max_length=10000)]
IncidentId = Annotated[str | None, Field(pattern=r"^INC-[0-9]{4,}$")]
DeploymentId = Annotated[str, Field(pattern=r"^dep-[0-9]+$")]
ApprovalId = Annotated[
    str,
    Field(
        pattern=r"^apr-[0-9a-f]{12}$",
        description="Id of a remediation a human approved (GET /agents/{run_id}/approval)",
    ),
]
