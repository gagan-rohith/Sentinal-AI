"""Pure routing functions. They read state and never modify it."""

from typing import Literal

from agents.schemas import CriticVerdict
from core.enums import ApprovalStatus
from graph.state import IncidentState, Stage

AfterCritic = Literal["retrieval", "root_cause", "remediation", "human_approval", "postmortem"]

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
        # Any production change goes past a human first, even with open critic issues;
        # those issues are shown to the approver.
        return "human_approval" if state.get("approval_required") else "postmortem"
    return _RETRY_TARGET[review.verdict]


def route_after_approval(state: IncidentState) -> Literal["action_execution", "postmortem"]:
    if state.get("approval_status") is ApprovalStatus.APPROVED:
        return "action_execution"
    return "postmortem"
