import re
from typing import Any, TypeVar

from pydantic import BaseModel

from core.exceptions import SentinelError
from graph.state import AgentDeps
from retrieval.bm25 import tokenize
from tools.tool_registry import ToolCallRecord

T = TypeVar("T", bound=BaseModel)

# Words that appear in almost every incident and carry no signal for matching.
_GENERIC = frozenset(
    {
        "error", "errors", "request", "requests", "service", "failed", "failing", "api",
        "http", "response", "responses", "incident", "rate", "high", "time", "timeout",
        "after", "during",
    }
)  # fmt: skip


async def try_tool(
    deps: AgentDeps,
    name: str,
    arguments: dict[str, Any],
    output_type: type[T],
    calls: list[ToolCallRecord],
    gaps: list[str],
) -> T | None:
    """Call a tool; an expected failure becomes a recorded data gap instead of ending the run."""
    try:
        result = await deps.tools.invoke(name, arguments, deps.principal, recorder=calls)
    except SentinelError as exc:
        gaps.append(f"{name} failed ({exc.code}): {exc.message}")
        return None
    output = result.output
    if not isinstance(output, output_type):
        raise TypeError(f"{name} returned {type(output).__name__}, expected {output_type.__name__}")
    return output


def keywords(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _GENERIC and not t.isdigit() and len(t) > 2}


def first_sentence(text: str, limit: int = 90) -> str:
    sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 3].rsplit(" ", 1)[0] + "..."
