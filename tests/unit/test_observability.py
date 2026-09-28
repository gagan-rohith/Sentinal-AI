import io
import json
import logging
import os
from collections.abc import Iterator

import pytest
import structlog
from pydantic import SecretStr

from agents.schemas import AgentCall
from observability import metrics
from observability.costs import estimate_cost
from observability.langsmith import configure_langsmith
from observability.logging import configure_logging
from observability.tracing import accept_trace_id, current_trace_id, new_trace_id


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    yield
    structlog.contextvars.clear_contextvars()
    configure_logging("INFO", "console")


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_json_logs_carry_bound_context() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream=stream)
    structlog.contextvars.bind_contextvars(trace_id="abc12345", run_id="run-1")
    structlog.get_logger("test").info("something_happened", detail=3)

    [entry] = lines(stream)
    assert entry["event"] == "something_happened"
    assert entry["trace_id"] == "abc12345"
    assert entry["run_id"] == "run-1"
    assert entry["level"] == "info"
    assert entry["detail"] == 3
    assert "timestamp" in entry


def test_stdlib_loggers_share_the_json_format() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream=stream)
    structlog.contextvars.bind_contextvars(trace_id="std12345")
    logging.getLogger("uvicorn.error").warning("from the standard library")

    [entry] = lines(stream)
    assert entry["event"] == "from the standard library"
    assert entry["level"] == "warning"
    assert entry["trace_id"] == "std12345"


def test_level_filtering() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", "json", stream=stream)
    structlog.get_logger("test").info("hidden")
    structlog.get_logger("test").warning("shown")
    assert [e["event"] for e in lines(stream)] == ["shown"]


def test_exceptions_are_rendered() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream=stream)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger("test").exception("crashed")
    [entry] = lines(stream)
    assert "RuntimeError: boom" in str(entry["exception"])


@pytest.mark.parametrize(
    ("header", "kept"),
    [("abc12345", True), ("trace-id_1.2", True), ("short", False), ("bad id!", False),
     (None, False), ("x" * 65, False)],
)  # fmt: skip
def test_incoming_trace_ids_are_validated(header: str | None, kept: bool) -> None:
    accepted = accept_trace_id(header)
    assert (accepted == header) is kept
    assert len(new_trace_id()) == 32


def test_current_trace_id_reads_the_logging_context() -> None:
    assert current_trace_id() is None
    structlog.contextvars.bind_contextvars(trace_id="ctx12345")
    assert current_trace_id() == "ctx12345"


def _sample(name: str, labels: dict[str, str]) -> float:
    value = metrics.REGISTRY.get_sample_value(name, labels)
    return value or 0.0


def test_agent_calls_record_tokens_and_cost() -> None:
    labels = {"agent": "triage", "model": "claude-sonnet-5", "direction": "input"}
    before_tokens = _sample("sentinel_llm_tokens_total", labels)
    before_cost = _sample("sentinel_llm_cost_usd_total", {"model": "claude-sonnet-5"})
    metrics.record_agent_call(
        AgentCall(agent="triage", mode="llm", model="claude-sonnet-5", latency_ms=12.0,
                  input_tokens=1000, output_tokens=200)
    )  # fmt: skip
    assert _sample("sentinel_llm_tokens_total", labels) - before_tokens == 1000
    cost = _sample("sentinel_llm_cost_usd_total", {"model": "claude-sonnet-5"}) - before_cost
    assert cost == pytest.approx(estimate_cost("claude-sonnet-5", 1000, 200))


def test_heuristic_calls_record_no_tokens() -> None:
    labels = {"agent": "critic", "mode": "heuristic"}
    before = _sample("sentinel_agent_calls_total", labels)
    metrics.record_agent_call(AgentCall(agent="critic", mode="heuristic", model=None, latency_ms=1))
    assert _sample("sentinel_agent_calls_total", labels) - before == 1


def test_run_and_approval_counters() -> None:
    before_runs = _sample("sentinel_runs_total", {"outcome": "completed"})
    before_retries = _sample("sentinel_critic_retries_total", {})
    before_approved = _sample("sentinel_approval_decisions_total", {"decision": "approved"})
    metrics.record_run("completed", retries=2)
    metrics.record_approval(approved=True)
    assert _sample("sentinel_runs_total", {"outcome": "completed"}) - before_runs == 1
    assert _sample("sentinel_critic_retries_total", {}) - before_retries == 2
    assert (
        _sample("sentinel_approval_decisions_total", {"decision": "approved"}) - before_approved
        == 1
    )


# These tests use a private mapping: setting LANGSMITH_* in os.environ would switch on
# real tracing for every later test in the process.


def test_langsmith_stays_off_without_a_key() -> None:
    env: dict[str, str] = {}
    assert configure_langsmith(None, "p", env) is False
    assert configure_langsmith(SecretStr(""), "p", env) is False
    assert env == {}


def test_langsmith_turns_on_with_a_key() -> None:
    env: dict[str, str] = {}
    assert configure_langsmith(SecretStr("ls-test-key"), "sentinel-test", env) is True
    assert env == {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "ls-test-key",
        "LANGSMITH_PROJECT": "sentinel-test",
    }


def test_test_session_never_traces() -> None:
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert "LANGSMITH_API_KEY" not in os.environ
