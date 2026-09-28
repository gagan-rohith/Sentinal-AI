"""MCP server exposing SentinelAI's operational tools.

Run over stdio (for Claude Desktop and other local clients):

    python -m mcp_server.server

or over streamable HTTP:

    python -m mcp_server.server --transport streamable-http --port 8765

Every tool is a thin adapter over the same ToolRegistry the API and agents use, so
permission checks, input validation, timeouts and the approval gate are identical.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from typing import Any, TypeVar

import structlog
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from auth.api_keys import ApiKeyAuthenticator
from core.enums import LogLevel, Severity
from core.exceptions import SentinelError
from core.models import ServiceHealth
from mcp_server.auth import resolve_principal
from mcp_server.schemas import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    ApprovalId,
    DeploymentId,
    Description,
    EndTime,
    IncidentId,
    LogLimit,
    Minutes,
    Query,
    Service,
    Title,
    TopK,
)
from tools.common import ActionResult
from tools.deployments import DeploymentStatusResult
from tools.logs import LogsResult
from tools.metrics import MetricsResult
from tools.search import SearchResults
from tools.tickets import Ticket
from tools.tool_registry import ToolRegistry

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

INSTRUCTIONS = (
    "Operational tools for investigating production incidents: logs, metrics, service "
    "health, deployments, runbooks and past incidents. restart_service and "
    "rollback_deployment change production state; they only run for an admin key with an "
    "approval_id from a remediation that a human already approved."
)


def build_server(
    tools: ToolRegistry,
    authenticator: ApiKeyAuthenticator,
    env: Mapping[str, str] | None = None,
) -> MCPServer:
    environment = os.environ if env is None else env
    server = MCPServer(name="sentinel-ai", version="0.1.0", instructions=INSTRUCTIONS)

    async def call(
        ctx: Context,
        tool: str,
        arguments: dict[str, Any],
        output_type: type[T],
        approval_id: str | None = None,
    ) -> T:
        try:
            principal = resolve_principal(authenticator, ctx.headers, environment)
            result = await tools.invoke(tool, arguments, principal, approval_id=approval_id)
        except SentinelError as exc:
            log.info("mcp_tool_refused", tool=tool, code=exc.code, error=exc.message)
            # A structured error the model can read and act on.
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
            raise ToolError(json.dumps({"error": error}, default=str)) from exc
        if not isinstance(result.output, output_type):
            raise TypeError(f"{tool} returned {type(result.output).__name__}")
        return result.output

    @server.tool(annotations=READ_ONLY)
    async def search_logs(
        service: Service,
        ctx: Context,
        minutes: Minutes = 30,
        min_level: LogLevel = LogLevel.WARN,
        end_time: EndTime = None,
        limit: LogLimit = 100,
    ) -> LogsResult:
        """Log lines for a service in a time window, with the most frequent error patterns."""
        args = {"service": service, "minutes": minutes, "min_level": min_level,
                "end_time": end_time, "limit": limit}  # fmt: skip
        return await call(ctx, "get_recent_logs", args, LogsResult)

    @server.tool(annotations=READ_ONLY)
    async def get_metrics(
        service: Service, ctx: Context, minutes: Minutes = 30, end_time: EndTime = None
    ) -> MetricsResult:
        """Metric series for a service with a baseline comparison that flags anomalies."""
        args = {"service": service, "minutes": minutes, "end_time": end_time}
        return await call(ctx, "get_service_metrics", args, MetricsResult)

    @server.tool(annotations=READ_ONLY)
    async def get_service_health(
        service: Service, ctx: Context, end_time: EndTime = None
    ) -> ServiceHealth:
        """Health status of a service (healthy, degraded or down) and the reasons."""
        args = {"service": service, "end_time": end_time}
        return await call(ctx, "get_service_health", args, ServiceHealth)

    @server.tool(annotations=READ_ONLY)
    async def search_runbooks(query: Query, ctx: Context, top_k: TopK = 5) -> SearchResults:
        """Hybrid (keyword and semantic) search over operational runbooks."""
        return await call(ctx, "search_runbooks", {"query": query, "top_k": top_k}, SearchResults)

    @server.tool(annotations=READ_ONLY)
    async def search_incidents(
        query: Query,
        ctx: Context,
        top_k: TopK = 5,
        exclude_incident_ids: list[str] | None = None,
    ) -> SearchResults:
        """Search resolved incidents, including their recorded root cause and remediation."""
        args = {"query": query, "top_k": top_k, "exclude_incident_ids": exclude_incident_ids or []}
        return await call(ctx, "search_similar_incidents", args, SearchResults)

    @server.tool(annotations=READ_ONLY)
    async def get_deployment_status(
        service: Service, ctx: Context, end_time: EndTime = None
    ) -> DeploymentStatusResult:
        """The running and previous deployment of a service, and minutes since it deployed."""
        args = {"service": service, "end_time": end_time}
        return await call(ctx, "get_deployment_status", args, DeploymentStatusResult)

    @server.tool(annotations=WRITES)
    async def create_ticket(
        title: Title,
        service: Service,
        severity: Severity,
        description: Description,
        ctx: Context,
        incident_id: IncidentId = None,
    ) -> Ticket:
        """Open a ticket in the ticketing system. Requires an operator key."""
        args = {"title": title, "service": service, "severity": severity,
                "description": description, "incident_id": incident_id}  # fmt: skip
        return await call(ctx, "create_incident_ticket", args, Ticket)

    @server.tool(annotations=DESTRUCTIVE)
    async def restart_service(
        service: Service, approval_id: ApprovalId, ctx: Context
    ) -> ActionResult:
        """Rolling restart of a service. Admin only, and only with an approved approval_id.

        Each approved action can run once. Without a matching approval the call is refused
        with approval_required.
        """
        return await call(
            ctx, "restart_service", {"service": service}, ActionResult, approval_id=approval_id
        )

    @server.tool(annotations=DESTRUCTIVE)
    async def rollback_deployment(
        service: Service,
        deployment_id: DeploymentId,
        approval_id: ApprovalId,
        ctx: Context,
    ) -> ActionResult:
        """Roll a service back to the deployment before deployment_id. Admin only, with approval."""
        args = {"service": service, "deployment_id": deployment_id}
        return await call(ctx, "rollback_deployment", args, ActionResult, approval_id=approval_id)

    return server


def _log_to_stderr() -> None:
    # stdout carries the MCP protocol over stdio; anything else written there corrupts it.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))


async def _serve(transport: str, host: str, port: int) -> None:
    from app.config import get_settings
    from app.container import Container

    container = await Container.create(get_settings())
    server = build_server(container.tools, container.api_keys)
    try:
        if transport == "stdio":
            await server.run_stdio_async()
        else:
            await server.run_streamable_http_async(host=host, port=port)
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="SentinelAI MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    _log_to_stderr()
    asyncio.run(_serve(args.transport, args.host, args.port))


if __name__ == "__main__":
    main()
