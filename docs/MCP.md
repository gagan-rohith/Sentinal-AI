# MCP server

SentinelAI exposes its operational tools over the [Model Context Protocol](https://modelcontextprotocol.io),
so Claude Desktop, Claude Code or any other MCP client can investigate incidents with the
same tools the agents use.

The server is a thin adapter over the tool registry (`tools/tool_registry.py`). Permission
checks, input validation, timeouts and the approval gate are the same code path as the REST
API and the LangGraph agents; MCP adds no second place where safety is decided.

## Tools

| Tool | Wraps | Needs | Changes state |
|---|---|---|---|
| `search_logs` | `get_recent_logs` | operator | no |
| `get_metrics` | `get_service_metrics` | operator | no |
| `get_service_health` | `get_service_health` | operator | no |
| `search_runbooks` | `search_runbooks` | operator | no |
| `search_incidents` | `search_similar_incidents` | operator | no |
| `get_deployment_status` | `get_deployment_status` | operator | no |
| `create_ticket` | `create_incident_ticket` | operator | yes (ticket only) |
| `restart_service` | `restart_service` | admin + approval | yes, destructive |
| `rollback_deployment` | `rollback_deployment` | admin + approval | yes, destructive |

Every tool declares an input schema and an output schema, and returns structured content.
Read-only tools carry `readOnlyHint`; the two production-changing tools carry `destructiveHint`,
so well-behaved clients ask the user before calling them.

## Destructive-action safeguards

`restart_service` and `rollback_deployment` run only when all of these hold:

1. The caller's key has the `admin` role.
2. The call includes an `approval_id` for a remediation a human approved through the
   approval workflow (`POST /agents/{run_id}/approve`).
3. The tool and arguments match an action listed in that approval.
4. That action has not already run. Approvals are single use, so an approval cannot be
   replayed through MCP after the workflow executed it.

Anything else returns a tool error with a structured body the model can read, for example:

```json
{"error": {"code": "approval_required", "message": "tool 'restart_service' changes production state and needs an approved request", "details": {"tool": "restart_service"}}}
```

In practice approved actions are executed by the workflow itself, so from MCP these tools are
refused almost always. That is intentional: an assistant connected over MCP can investigate
freely but can never change production on its own.

## Authentication

| Transport | Where the key comes from |
|---|---|
| stdio | `SENTINEL_API_KEY` environment variable, set by the client in its server config |
| streamable HTTP | `X-API-Key` header, or `Authorization: Bearer <key>` on each request |

Keys are the same role-mapped API keys the REST API uses. Generate one with
`python -m auth.api_keys operator` and add its config line to `API_KEYS` in `.env`.
Give an assistant an `operator` key; there is rarely a reason to give it `admin`.

## Running

```bash
# stdio (what desktop clients launch)
python -m mcp_server.server

# streamable HTTP on http://127.0.0.1:8765/mcp
python -m mcp_server.server --transport streamable-http --port 8765
```

The server reads the same `.env` as the API: search backend, embedding model, database path.
Over stdio all logs go to stderr, because stdout carries the protocol.

## Connecting Claude Desktop

Open Claude Desktop, go to Settings > Developer > Edit Config, and add the server to
`claude_desktop_config.json`. Use absolute paths. On Windows:

```json
{
  "mcpServers": {
    "sentinel-ai": {
      "command": "C:\\path\\to\\sentinel-ai\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\path\\to\\sentinel-ai",
      "env": {
        "PYTHONPATH": "C:\\path\\to\\sentinel-ai",
        "SENTINEL_API_KEY": "sk_sentinel_your_operator_key"
      }
    }
  }
}
```

On macOS or Linux, use `.venv/bin/python` and forward slashes. Restart Claude Desktop; the
tools appear under the tools menu. Try:

> checkout-api is throwing 503s. Check its health, logs and recent deployments at
> 2026-04-30T08:47:00Z, find the matching runbook and similar past incidents, and tell me
> the most likely root cause.

If Elasticsearch is not running, set `SEARCH_BACKEND=memory` in the `env` block so the server
starts with the in-memory index.

## Connecting Claude Code

```bash
claude mcp add sentinel-ai --env SENTINEL_API_KEY=sk_sentinel_your_operator_key -- \
  /path/to/sentinel-ai/.venv/bin/python -m mcp_server.server
```

Or, with the HTTP transport running:

```bash
claude mcp add --transport http sentinel-ai http://127.0.0.1:8765/mcp \
  --header "X-API-Key: sk_sentinel_your_operator_key"
```

## Inspecting

The MCP Inspector lists tools and lets you call them by hand:

```bash
npx @modelcontextprotocol/inspector python -m mcp_server.server
```
