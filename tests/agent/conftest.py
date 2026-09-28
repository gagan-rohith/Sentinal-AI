import asyncio
from collections import defaultdict, deque
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from agents.llm import Usage
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import LLMUnavailableError
from core.models import Incident
from graph.incident_graph import RECURSION_LIMIT, build_incident_graph
from graph.state import AgentDeps, IncidentState, Stage
from retrieval.hybrid_search import HybridSearcher
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import ToolRegistry, build_default_registry

T = TypeVar("T", bound=BaseModel)


class ScriptedLLM:
    """Returns queued responses per schema; anything not scripted is 'unavailable'.

    Unscripted agents therefore fall back to their heuristics, which is also how the
    fallback path gets exercised.
    """

    model = "scripted-test-model"

    def __init__(self, **responses: list[BaseModel]) -> None:
        self.queues: dict[str, deque[BaseModel]] = defaultdict(deque)
        for schema_name, items in responses.items():
            self.queues[schema_name].extend(items)
        self.calls: list[str] = []

    async def generate(self, schema: type[T], system: str, prompt: str) -> tuple[T, Usage]:
        self.calls.append(schema.__name__)
        queue = self.queues.get(schema.__name__)
        if not queue:
            raise LLMUnavailableError(f"{schema.__name__} not scripted")
        item = queue[0] if len(queue) == 1 else queue.popleft()
        if not isinstance(item, schema):
            raise TypeError(f"scripted {type(item).__name__} for {schema.__name__}")
        return item, Usage(input_tokens=100, output_tokens=20)


@pytest.fixture(scope="session")
def registry(backend: SimulatedOpsBackend, searcher: HybridSearcher) -> ToolRegistry:
    return build_default_registry(backend, TicketStore(), searcher)


@pytest.fixture
def heuristic_deps(registry: ToolRegistry) -> AgentDeps:
    return AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL)


@pytest.fixture(scope="session")
def demo_state(registry: ToolRegistry, demo_incident: Incident) -> dict[str, Any]:
    """Final state of a heuristic run on the demo incident, shared read-only by tests."""
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL)
    return asyncio.run(run_graph(deps, demo_incident))


async def run_graph(deps: AgentDeps, incident: Incident) -> dict[str, Any]:
    graph = build_incident_graph(deps)
    initial: IncidentState = {"run_id": "run-test", "incident": incident, "stage": Stage.START}
    result: dict[str, Any] = await graph.ainvoke(initial, {"recursion_limit": RECURSION_LIMIT})
    return result
