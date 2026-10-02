from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.approval import action_execution_node, human_approval_node
from agents.context_collection import context_collection_node
from agents.critic_agent import critic_node
from agents.postmortem_agent import postmortem_node
from agents.remediation_agent import remediation_node
from agents.retrieval_agent import retrieval_node
from agents.root_cause_agent import root_cause_node
from agents.supervisor import supervisor_node
from agents.triage_agent import triage_node
from critic_service.client import remote_critic_node
from graph.routing import route_after_approval, route_after_critic, route_from_supervisor
from graph.state import AgentDeps, IncidentState

NodeFn = Callable[[AgentDeps, IncidentState], Awaitable[dict[str, Any]]]

# Worst case: 8 nodes on the first pass plus 4 per critic retry. Anything above this
# limit is a bug, and LangGraph raises GraphRecursionError instead of looping forever.
RECURSION_LIMIT = 50


class _Node(Protocol):
    # LangGraph's node protocol names the parameter "state", which Callable cannot express.
    def __call__(self, state: IncidentState) -> Awaitable[dict[str, Any]]: ...


def _bind(fn: NodeFn, deps: AgentDeps) -> _Node:
    async def node(state: IncidentState) -> dict[str, Any]:
        return await fn(deps, state)

    node.__name__ = fn.__name__
    return node


def build_incident_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[IncidentState, None, IncidentState, IncidentState]:
    """A checkpointer is required: the approval gate pauses the run and resumes it later."""
    graph = StateGraph(IncidentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("triage", _bind(triage_node, deps))
    graph.add_node("context_collection", _bind(context_collection_node, deps))
    graph.add_node("retrieval", _bind(retrieval_node, deps))
    graph.add_node("root_cause", _bind(root_cause_node, deps))
    graph.add_node("remediation", _bind(remediation_node, deps))
    # The same "critic" node either way, so routing, stages and reports do not change.
    critic = remote_critic_node if deps.critic is not None else critic_node
    graph.add_node("critic", _bind(critic, deps))
    graph.add_node("human_approval", _bind(human_approval_node, deps))
    graph.add_node("action_execution", _bind(action_execution_node, deps))
    graph.add_node("postmortem", _bind(postmortem_node, deps))

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_from_supervisor, ["triage", "retrieval"])
    graph.add_edge("triage", "context_collection")
    graph.add_edge("context_collection", "supervisor")
    graph.add_edge("retrieval", "root_cause")
    graph.add_edge("root_cause", "remediation")
    graph.add_edge("remediation", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        ["retrieval", "root_cause", "remediation", "human_approval", "postmortem"],
    )
    graph.add_conditional_edges(
        "human_approval", route_after_approval, ["action_execution", "postmortem"]
    )
    graph.add_edge("action_execution", "postmortem")
    graph.add_edge("postmortem", END)
    return graph.compile(checkpointer=checkpointer)
