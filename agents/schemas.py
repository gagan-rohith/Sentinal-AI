"""Structured outputs of each agent.

These models double as the JSON schemas Claude is constrained to, so they avoid
open-ended dicts and keep every field explicit.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from agents.evidence import Evidence
from core.enums import ApprovalStatus, Role, Severity


class Subsystem(StrEnum):
    DATABASE = "database"
    CACHE = "cache"
    NETWORK = "network"
    AUTH = "auth"
    COMPUTE = "compute"
    STORAGE = "storage"
    QUEUE = "queue"
    DEPLOYMENT = "deployment"
    CONFIG = "config"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class TriageSummary(BaseModel):
    summary: str
    assessed_severity: Severity
    severity_reason: str
    subsystem: Subsystem
    key_symptoms: list[str]


class SearchPlan(BaseModel):
    queries: list[str] = Field(description="2 or 3 focused search queries")


class Hypothesis(BaseModel):
    title: str
    description: str
    category: str | None = Field(
        default=None,
        description="Category label of a matching past incident, if one applies",
    )
    evidence_for: list[str] = Field(description="Evidence ids that support this hypothesis")
    evidence_against: list[str] = Field(description="Evidence ids that argue against it")
    confidence: float = Field(ge=0, le=1)


class RootCauseAnalysis(BaseModel):
    hypotheses: list[Hypothesis] = Field(description="3 to 5 hypotheses, most likely first")
    selected_index: int = Field(ge=0, description="Index of the chosen hypothesis")
    reasoning: str

    @property
    def selected(self) -> Hypothesis:
        return self.hypotheses[min(self.selected_index, len(self.hypotheses) - 1)]


class StepKind(StrEnum):
    DIAGNOSTIC = "diagnostic"
    MITIGATION = "mitigation"
    FIX = "fix"
    PREVENTION = "prevention"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


ActionTool = Literal["restart_service", "rollback_deployment"]


class ToolAction(BaseModel):
    tool: ActionTool
    service: str
    deployment_id: str | None = Field(
        default=None, description="Required for rollback_deployment: the deployment to undo"
    )

    def arguments(self) -> dict[str, str]:
        args = {"service": self.service}
        if self.deployment_id:
            args["deployment_id"] = self.deployment_id
        return args


class RemediationStep(BaseModel):
    description: str
    kind: StepKind
    risk: Risk
    action: ToolAction | None = None
    evidence: list[str] = Field(default_factory=list, description="Evidence ids this relies on")


class RemediationPlan(BaseModel):
    summary: str
    steps: list[RemediationStep]
    rollback_plan: str
    overall_risk: Risk
    # Set in code from the tool registry, never trusted from the model.
    approval_required: bool = False


class CriticVerdict(StrEnum):
    APPROVE = "approve"
    NEED_MORE_EVIDENCE = "need_more_evidence"
    REVISE_ROOT_CAUSE = "revise_root_cause"
    REVISE_REMEDIATION = "revise_remediation"


class CriticReview(BaseModel):
    verdict: CriticVerdict
    confidence: float = Field(ge=0, le=1)
    issues: list[str]
    unsupported_claims: list[str] = Field(default_factory=list)


class PostmortemDraft(BaseModel):
    title: str
    summary: str
    impact: str
    root_cause: str
    remediation: str
    prevention: list[str]
    open_questions: list[str]


class TimelineEvent(BaseModel):
    timestamp: datetime
    description: str
    source: str


class ProposedAction(BaseModel):
    tool: str
    arguments: dict[str, str]
    description: str
    risk: Risk


class ApprovalRequest(BaseModel):
    """What a human sees before deciding whether a production change may run."""

    run_id: str
    incident_id: str
    service: str
    root_cause: str
    root_cause_confidence: float
    actions: list[ProposedAction]
    overall_risk: Risk
    rollback_plan: str
    unresolved_critic_issues: list[str]


class ApprovalDecision(BaseModel):
    approval_id: str
    approved: bool
    decided_by: str
    role: Role
    comment: str | None = None
    decided_at: datetime


class ExecutedAction(BaseModel):
    tool: str
    arguments: dict[str, str]
    status: Literal["succeeded", "failed"]
    message: str
    executed_at: datetime


class AgentCall(BaseModel):
    agent: str
    mode: Literal["llm", "heuristic", "fallback"]
    model: str | None
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


class FinalReport(BaseModel):
    run_id: str
    incident_id: str
    trace_id: str | None = None
    postmortem: PostmortemDraft
    timeline: list[TimelineEvent]
    selected_root_cause: Hypothesis
    hypotheses: list[Hypothesis]
    remediation_plan: RemediationPlan
    approval_status: ApprovalStatus
    approval: ApprovalDecision | None
    executed_actions: list[ExecutedAction]
    critic_review: CriticReview | None
    unresolved_critic_issues: bool
    retries: int
    data_gaps: list[str]
    evidence: list[Evidence]
    evidence_ids_cited: list[str]
    agent_calls: list[AgentCall]
    tool_call_count: int
    mode: Literal["llm", "heuristic", "mixed"]
