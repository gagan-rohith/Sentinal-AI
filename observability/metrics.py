"""Prometheus metrics.

Labels are bounded on purpose: route templates rather than raw paths, tool and agent
names rather than arguments, so cardinality stays fixed no matter the traffic.
"""

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client.exposition import generate_latest

from agents.schemas import AgentCall
from observability.costs import estimate_cost

REGISTRY = CollectorRegistry(auto_describe=True)
PREFIX = "sentinel"
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

http_requests = Counter(
    f"{PREFIX}_http_requests_total", "HTTP requests.", ["method", "route", "status"],
    registry=REGISTRY,
)  # fmt: skip
http_latency = Histogram(
    f"{PREFIX}_http_request_duration_seconds", "HTTP request latency.", ["method", "route"],
    buckets=LATENCY_BUCKETS, registry=REGISTRY,
)  # fmt: skip
tool_calls = Counter(
    f"{PREFIX}_tool_calls_total", "Tool registry calls.", ["tool", "status"], registry=REGISTRY
)
tool_latency = Histogram(
    f"{PREFIX}_tool_call_duration_seconds", "Tool call latency.", ["tool"],
    buckets=LATENCY_BUCKETS, registry=REGISTRY,
)  # fmt: skip
agent_calls = Counter(
    f"{PREFIX}_agent_calls_total", "Agent steps, by mode (llm, heuristic, fallback).",
    ["agent", "mode"], registry=REGISTRY,
)  # fmt: skip
agent_latency = Histogram(
    f"{PREFIX}_agent_call_duration_seconds", "Agent step latency.", ["agent", "mode"],
    buckets=LATENCY_BUCKETS, registry=REGISTRY,
)  # fmt: skip
llm_tokens = Counter(
    f"{PREFIX}_llm_tokens_total", "LLM tokens.", ["agent", "model", "direction"],
    registry=REGISTRY,
)  # fmt: skip
llm_cost = Counter(
    f"{PREFIX}_llm_cost_usd_total", "Estimated LLM cost at list price.", ["model"],
    registry=REGISTRY,
)  # fmt: skip
runs = Counter(
    f"{PREFIX}_runs_total",
    "Incident analysis runs by outcome (completed, failed, awaiting_approval).",
    ["outcome"], registry=REGISTRY,
)  # fmt: skip
critic_retries = Counter(
    f"{PREFIX}_critic_retries_total", "Critic-requested retries in completed runs.",
    registry=REGISTRY,
)  # fmt: skip
approvals = Counter(
    f"{PREFIX}_approval_decisions_total", "Human approval decisions.", ["decision"],
    registry=REGISTRY,
)  # fmt: skip


def record_http(method: str, route: str, status: int, seconds: float) -> None:
    http_requests.labels(method, route, str(status)).inc()
    http_latency.labels(method, route).observe(seconds)


def record_tool_call(tool: str, status: str, latency_ms: float) -> None:
    tool_calls.labels(tool, status).inc()
    tool_latency.labels(tool).observe(latency_ms / 1000)


def record_agent_call(call: AgentCall) -> None:
    agent_calls.labels(call.agent, call.mode).inc()
    agent_latency.labels(call.agent, call.mode).observe(call.latency_ms / 1000)
    if call.model and (call.input_tokens or call.output_tokens):
        llm_tokens.labels(call.agent, call.model, "input").inc(call.input_tokens)
        llm_tokens.labels(call.agent, call.model, "output").inc(call.output_tokens)
        cost = estimate_cost(call.model, call.input_tokens, call.output_tokens)
        if cost:
            llm_cost.labels(call.model).inc(cost)


def record_run(outcome: str, retries: int = 0) -> None:
    runs.labels(outcome).inc()
    if retries:
        critic_retries.inc(retries)


def record_approval(approved: bool) -> None:
    approvals.labels("approved" if approved else "rejected").inc()


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
