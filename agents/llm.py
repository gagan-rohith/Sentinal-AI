import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
import structlog
from pydantic import BaseModel, ValidationError

from agents.schemas import AgentCall
from core.exceptions import LLMUnavailableError

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class StructuredLLM(Protocol):
    model: str

    async def generate(self, schema: type[T], system: str, prompt: str) -> tuple[T, Usage]: ...


class AnthropicLLM:
    """Claude through the official SDK with structured outputs."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        max_tokens: int = 16000,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        # api_key=None lets the SDK resolve credentials from the environment or a profile.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    async def generate(self, schema: type[T], system: str, prompt: str) -> tuple[T, Usage]:
        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError(f"rate limited by the Claude API: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(
                f"Claude API returned {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"could not reach the Claude API: {exc}") from exc
        except ValidationError as exc:
            raise LLMUnavailableError(f"response did not match {schema.__name__}") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailableError("the model declined the request")
        if response.parsed_output is None:
            raise LLMUnavailableError(f"no {schema.__name__} in response ({response.stop_reason})")
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        return response.parsed_output, usage


async def run_step(
    agent: str,
    llm: StructuredLLM | None,
    schema: type[T],
    system: str,
    prompt: Callable[[], str],
    heuristic: Callable[[], T],
) -> tuple[T, AgentCall]:
    """Run one agent step with Claude, or with the deterministic heuristic.

    A failed Claude call falls back to the heuristic and is recorded as mode="fallback",
    so degraded runs are visible in the report and the benchmark.
    """
    started = time.perf_counter()

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    if llm is None:
        result = heuristic()
        return result, AgentCall(agent=agent, mode="heuristic", model=None, latency_ms=elapsed())

    try:
        result, usage = await llm.generate(schema, system, prompt())
    except LLMUnavailableError as exc:
        log.warning("llm_fallback", agent=agent, error=exc.message)
        result = heuristic()
        return result, AgentCall(
            agent=agent, mode="fallback", model=llm.model, latency_ms=elapsed(), error=exc.message
        )
    return result, AgentCall(
        agent=agent,
        mode="llm",
        model=llm.model,
        latency_ms=elapsed(),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
