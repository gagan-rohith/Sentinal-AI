"""Pure routing functions. They read state and never modify it."""

from typing import Literal

from agents.schemas import CriticVerdict
from graph.state import IncidentState, Stage

AfterCritic = Literal["retrieval", "root_cause", "remediation", "postmortem"]

_RETRY_TARGET: dict[CriticVerdict, AfterCritic] = {
    CriticVerdict.NEED_MORE_EVIDENCE: "retrieval",
    CriticVerdict.REVISE_ROOT_CAUSE: "root_cause",
    CriticVerdict.REVISE_REMEDIATION: "remediation",
}


def route_from_supervisor(state: IncidentState) -> Literal["triage", "retrieval"]:
    return "triage" if state.get("stage", Stage.START) == Stage.START else "retrieval"


def route_after_critic(state: IncidentState) -> AfterCritic:
    review = state["critic_feedback"]
    # The critic node sets this once the retry budget is spent.
    if review.verdict is CriticVerdict.APPROVE or state.get("unresolved_critic_issues"):
        return "postmortem"
    return _RETRY_TARGET[review.verdict]
