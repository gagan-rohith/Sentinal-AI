"""The review_remediation_plan skill's wire contract, shared by the service and its client.

Requests and results travel as A2A data parts (JSON objects). Both sides validate them with
these models, so a malformed payload fails loudly instead of reaching the critic or the graph.
"""

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, Field

from agents.evidence import Evidence
from agents.schemas import (
    AgentCall,
    CriticReview,
    CriticVerdict,
    Hypothesis,
    RemediationPlan,
    Risk,
)

SKILL_ID = "review_remediation_plan"
RESULT_ARTIFACT = "review_result"
MEDIA_TYPE = "application/json"


class ReviewRequest(BaseModel):
    """The remediation plan plus the incident context the critic checks it against."""

    incident_id: str
    service: str
    remediation_plan: RemediationPlan
    selected_root_cause: Hypothesis
    root_cause_confidence: float = Field(ge=0, le=1)
    hypotheses: list[Hypothesis]
    evidence: list[Evidence]

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "ReviewRequest":
        incident = state["incident"]
        return cls(
            incident_id=incident.incident_id,
            service=incident.service,
            remediation_plan=state["remediation_plan"],
            selected_root_cause=state["selected_root_cause"],
            root_cause_confidence=state.get("root_cause_confidence", 0.0),
            hypotheses=state.get("root_cause_hypotheses", []),
            evidence=state.get("evidence", []),
        )

    def as_state(self) -> dict[str, Any]:
        """The graph state keys the critic reads."""
        return {
            "remediation_plan": self.remediation_plan,
            "selected_root_cause": self.selected_root_cause,
            "root_cause_confidence": self.root_cause_confidence,
            "root_cause_hypotheses": self.hypotheses,
            "evidence": self.evidence,
        }


class ReviewResult(BaseModel):
    """The verdict. approved, reasons and risk_level summarize it; verdict, confidence and
    unsupported_claims carry the full review so the orchestrator can route retries as the
    in-process critic does."""

    approved: bool
    reasons: list[str]
    risk_level: Risk
    verdict: CriticVerdict
    confidence: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = Field(default_factory=list)
    agent_call: AgentCall

    @classmethod
    def from_review(
        cls, review: CriticReview, call: AgentCall, plan: RemediationPlan
    ) -> "ReviewResult":
        return cls(
            approved=review.verdict is CriticVerdict.APPROVE,
            reasons=review.issues,
            risk_level=plan.overall_risk,
            verdict=review.verdict,
            confidence=review.confidence,
            unsupported_claims=review.unsupported_claims,
            agent_call=call,
        )

    def as_review(self) -> CriticReview:
        return CriticReview(
            verdict=self.verdict,
            confidence=self.confidence,
            issues=self.reasons,
            unsupported_claims=self.unsupported_claims,
        )


class RemoteCritic(Protocol):
    """What the graph needs from a remote critic. Raises CriticUnavailableError on failure."""

    async def review(self, request: ReviewRequest) -> ReviewResult: ...
