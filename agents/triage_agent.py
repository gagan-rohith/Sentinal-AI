from typing import Any

from agents import prompts
from agents.llm import run_step
from agents.schemas import Subsystem, TriageSummary
from core.enums import Severity
from core.models import Incident
from graph.state import AgentDeps, IncidentState

# Checked in order; the first subsystem with the most hits wins ties.
SUBSYSTEM_KEYWORDS: dict[Subsystem, tuple[str, ...]] = {
    Subsystem.DATABASE: ("postgres", "connection pool", "sql", "migration", "column", "query",
                         "database", "jdbc", "hikari", "password authentication"),
    Subsystem.CACHE: ("redis", "cache", "evict", "maxmemory"),
    Subsystem.NETWORK: ("dns", "lookup", "load balancer", "502", "target group", "resolve"),
    Subsystem.AUTH: ("jwt", "401", "token", "jwks", "tls", "certificate", "x509", "accessdenied",
                     "not authorized"),
    Subsystem.COMPUTE: ("oom", "memory", "cpu", "throttl", "crashloop", "hpa", "replicas"),
    Subsystem.STORAGE: ("disk", "no space", "ephemeral-storage"),
    Subsystem.QUEUE: ("kafka", "queue", "consumer", "sqs", "backlog"),
    Subsystem.DEPENDENCY: ("timeout calling", "circuitbreaker", "provider", "upstream"),
    Subsystem.CONFIG: ("feature flag", "configmap", "config", "flag"),
    Subsystem.DEPLOYMENT: ("deployment", "release", "rollout"),
}  # fmt: skip

TRIAGE_ESCALATION_ERROR_RATE = 50.0


def heuristic_triage(incident: Incident) -> TriageSummary:
    text = " ".join(
        [incident.title, incident.description, *incident.symptoms, *incident.error_messages]
    ).lower()
    scores = {s: sum(text.count(k) for k in words) for s, words in SUBSYSTEM_KEYWORDS.items()}
    best = max(scores, key=lambda s: scores[s])
    subsystem = best if scores[best] else Subsystem.UNKNOWN

    severity, reason = incident.severity, "consistent with the reported severity"
    error_rate = incident.metrics_summary.get("error_rate_pct", 0.0)
    if error_rate >= TRIAGE_ESCALATION_ERROR_RATE and incident.severity is not Severity.SEV1:
        severity = Severity.SEV1
        reason = f"error rate of {error_rate}% means most requests are failing"

    symptoms = incident.symptoms or incident.error_messages
    return TriageSummary(
        summary=(
            f"{incident.service} in {incident.environment}: {incident.title}. "
            f"{incident.description}"
        ),
        assessed_severity=severity,
        severity_reason=reason,
        subsystem=subsystem,
        key_symptoms=list(symptoms[:5]),
    )


def triage_prompt(incident: Incident) -> str:
    return (
        "Incident:\n"
        + incident.model_dump_json(
            indent=2,
            exclude={"ground_truth_root_cause", "root_cause_category", "expected_remediation",
                     "relevant_runbook_ids"},
        )
    )  # fmt: skip


async def triage_node(deps: AgentDeps, state: IncidentState) -> dict[str, Any]:
    incident = state["incident"]
    summary, call = await run_step(
        "triage",
        deps.llm,
        TriageSummary,
        prompts.TRIAGE,
        lambda: triage_prompt(incident),
        lambda: heuristic_triage(incident),
    )
    return {"triage_summary": summary, "agent_calls": [call]}
