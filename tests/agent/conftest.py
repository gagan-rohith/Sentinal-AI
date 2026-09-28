import asyncio
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from agents.llm import Usage
from agents.schemas import ApprovalDecision
from auth.permissions import AGENT_PRINCIPAL
from core.enums import Role
from core.exceptions import LLMUnavailableError
from core.models import Incident
from graph.checkpoint import serializer
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


class AllowAllApprovals:
    """Approval verifier that accepts everything, to test execution in isolation."""

    async def verify(self, approval_id: str, tool: str, arguments: Mapping[str, Any]) -> bool:
        return True


def decision(approved: bool, role: Role = Role.ADMIN) -> ApprovalDecision:
    return ApprovalDecision(
        approval_id="apr-test",
        approved=approved,
        decided_by=f"tester-{role.value}",
        role=role,
        comment=None if approved else "not during peak traffic",
        decided_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


REJECT = decision(approved=False)


@pytest.fixture(scope="session")
def registry(backend: SimulatedOpsBackend, searcher: HybridSearcher) -> ToolRegistry:
    return build_default_registry(backend, TicketStore(), searcher)


@pytest.fixture(scope="session")
def permissive_registry(backend: SimulatedOpsBackend, searcher: HybridSearcher) -> ToolRegistry:
    return build_default_registry(backend, TicketStore(), searcher, approvals=AllowAllApprovals())


@pytest.fixture
def heuristic_deps(registry: ToolRegistry) -> AgentDeps:
    return AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL)


@pytest.fixture(scope="session")
def demo_state(registry: ToolRegistry, demo_incident: Incident) -> dict[str, Any]:
    """Final state of a heuristic run on the demo incident whose restart was rejected."""
    deps = AgentDeps(tools=registry, llm=None, principal=AGENT_PRINCIPAL)
    return asyncio.run(run_graph(deps, demo_incident))


async def run_graph(
    deps: AgentDeps,
    incident: Incident,
    resume_with: ApprovalDecision | None = REJECT,
) -> dict[str, Any]:
    """Run the graph; if it pauses for approval, resume with `resume_with` (None: stay paused)."""
    graph = build_incident_graph(deps, InMemorySaver(serde=serializer()))
    config: Any = {"configurable": {"thread_id": "run-test"}, "recursion_limit": RECURSION_LIMIT}
    initial: IncidentState = {"run_id": "run-test", "incident": incident, "stage": Stage.START}
    await graph.ainvoke(initial, config)
    if resume_with is not None and (await graph.aget_state(config)).next:
        await graph.ainvoke(Command(resume=resume_with.model_dump(mode="json")), config)
    snapshot = await graph.aget_state(config)
    return {**snapshot.values, "__next__": snapshot.next}
