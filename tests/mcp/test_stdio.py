"""Launch the MCP server as a subprocess over stdio, the way Claude Desktop does.

Catches anything that writes to stdout (logs, progress bars, prints), which would
corrupt the protocol stream even though in-process tests pass.
"""

import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from auth.api_keys import hash_key
from mcp_server.auth import ENV_API_KEY

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


async def test_stdio_server_lists_and_calls_tools(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "DATABASE_PATH": str(tmp_path / "mcp.db"),
        "SEARCH_BACKEND": "memory",
        "EMBEDDING_PROVIDER": "hash",
        "LLM_PROVIDER": "heuristic",
        "API_KEYS": f"operator:{hash_key('stdio-operator')}",
        ENV_API_KEY: "stdio-operator",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server.server"], env=env, cwd=str(ROOT)
    )
    async with Client(params, read_timeout_seconds=120) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert len(tools) == 9
        health = await client.call_tool("get_service_health", {"service": "checkout-api"})
        assert not health.is_error
        assert health.structured_content is not None
        assert health.structured_content["service"] == "checkout-api"
