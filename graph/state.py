from dataclasses import dataclass
from operator import add
from typing import Annotated, TypedDict

from agents.evidence import Evidence
from agents.llm import StructuredLLM
from agents.schemas import (
    AgentCall,
    ApprovalDecision,
    ApprovalRequest,
    CriticReview,
    ExecutedAction,
    FinalReport,
    Hypothesis,
    RemediationPlan,
    TriageSummary,
)
from auth.permissions import Principal
from core.enums import ApprovalStatus
from core.models import Incident, ServiceHealth
from retrieval.models import SearchHit
from tools.deployments import DeploymentStatusResult, RecentDeploymentsResult
from tools.logs import LogsResult
from tools.metrics import MetricsResult
from tools.tool_registry import ToolCallRecord, ToolRegistry

MAX_RETRIES = 3


class Stage:
    START = "start"
    CONTEXT_COLLECTED = "context_collected"


class DeploymentContext(TypedDict):
    status: DeploymentStatusResult
    recent: RecentDeploymentsResult


class IncidentState(TypedDict, total=False):
    run_id: str
    trace_id: str
    incident: Incident
    stage: str

    triage_summary: TriageSummary
    service_health: ServiceHealth
    retrieved_logs: LogsResult
    retrieved_metrics: MetricsResult
    deployment_context: DeploymentContext

    search_queries: list[str]
    retrieved_runbooks: list[SearchHit]
    similar_incidents: list[SearchHit]
    service_docs: list[SearchHit]
    evidence: list[Evidence]

    root_cause_hypotheses: list[Hypothesis]
    selected_root_cause: Hypothesis
    root_cause_confidence: float
    remediation_plan: RemediationPlan
    critic_feedback: CriticReview
    retry_count: int
    unresolved_critic_issues: bool

    approval_required: bool
    approval_status: ApprovalStatus
    approval_request: ApprovalRequest
    approval_decision: ApprovalDecision
    tool_execution_result: list[ExecutedAction]
    final_report: FinalReport

    # Append-only across nodes.
    data_gaps: Annotated[list[str], add]
    tool_calls: Annotated[list[ToolCallRecord], add]
    agent_calls: Annotated[list[AgentCall], add]


@dataclass(frozen=True)
class AgentDeps:
    tools: ToolRegistry
    llm: StructuredLLM | None
    # Identity the agents use for tool calls. Never allowed to run destructive tools.
    principal: Principal
    max_retries: int = MAX_RETRIES
