"""Evaluation datasets.

Usage: python -m evals.datasets   (rebuilds evals/dataset/incidents.json)

incidents.json is derived from the synthetic incidents: one case per incident with its
ground truth. qa.json is hand-written: paraphrased questions that avoid the runbooks' own
wording, to test retrieval separately from the agents.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from core.models import Incident
from data.loader import load_incidents

DATASET_DIR = Path(__file__).resolve().parent / "dataset"


class IncidentCase(BaseModel):
    incident_id: str
    service: str
    category: str
    relevant_runbook_ids: list[str]
    expected_root_cause: str
    expected_remediation: str


class QACase(BaseModel):
    id: str
    query: str
    relevant_runbook_ids: list[str]


def case_for(incident: Incident) -> IncidentCase:
    if not (incident.root_cause_category and incident.ground_truth_root_cause):
        raise ValueError(f"{incident.incident_id} has no ground truth")
    return IncidentCase(
        incident_id=incident.incident_id,
        service=incident.service,
        category=incident.root_cause_category,
        relevant_runbook_ids=incident.relevant_runbook_ids,
        expected_root_cause=incident.ground_truth_root_cause,
        expected_remediation=incident.expected_remediation or "",
    )


def build_incident_cases(incidents: list[Incident] | None = None) -> list[IncidentCase]:
    return [case_for(i) for i in (incidents or load_incidents())]


def load_incident_cases(root: Path = DATASET_DIR) -> list[IncidentCase]:
    raw = json.loads((root / "incidents.json").read_text(encoding="utf-8"))
    return [IncidentCase.model_validate(item) for item in raw]


def load_qa_cases(root: Path = DATASET_DIR) -> list[QACase]:
    raw = json.loads((root / "qa.json").read_text(encoding="utf-8"))
    return [QACase.model_validate(item) for item in raw]


def main() -> None:
    cases = build_incident_cases()
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    (DATASET_DIR / "incidents.json").write_text(
        json.dumps([c.model_dump() for c in cases], indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(cases)} incident cases to {DATASET_DIR / 'incidents.json'}")


if __name__ == "__main__":
    main()
