import pytest

from agents.schemas import CriticReview, CriticVerdict
from graph.routing import route_after_critic, route_from_supervisor
from graph.state import IncidentState, Stage


def review(verdict: CriticVerdict) -> CriticReview:
    return CriticReview(verdict=verdict, confidence=0.5, issues=[])


def test_supervisor_routes_to_triage_first_then_retrieval() -> None:
    assert route_from_supervisor({"stage": Stage.START}) == "triage"
    assert route_from_supervisor({}) == "triage"
    assert route_from_supervisor({"stage": Stage.CONTEXT_COLLECTED}) == "retrieval"


@pytest.mark.parametrize(
    ("verdict", "target"),
    [
        (CriticVerdict.APPROVE, "postmortem"),
        (CriticVerdict.NEED_MORE_EVIDENCE, "retrieval"),
        (CriticVerdict.REVISE_ROOT_CAUSE, "root_cause"),
        (CriticVerdict.REVISE_REMEDIATION, "remediation"),
    ],
)
def test_critic_verdict_routing(verdict: CriticVerdict, target: str) -> None:
    state: IncidentState = {"critic_feedback": review(verdict)}
    assert route_after_critic(state) == target


@pytest.mark.parametrize("verdict", list(CriticVerdict))
def test_exhausted_retries_always_move_forward(verdict: CriticVerdict) -> None:
    state: IncidentState = {"critic_feedback": review(verdict), "unresolved_critic_issues": True}
    assert route_after_critic(state) == "postmortem"
