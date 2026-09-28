from agents.schemas import FinalReport, Hypothesis
from core.models import Incident
from graph.checkpoint import allowed_types, serializer


def test_allowlist_covers_state_types_only() -> None:
    allowed = allowed_types()
    assert ("core.models", "Incident") in allowed
    assert ("agents.schemas", "Hypothesis") in allowed
    assert ("core.enums", "Severity") in allowed
    assert all(
        module.split(".")[0] in {"agents", "core", "retrieval", "tools"} for module, _ in allowed
    )


def test_state_objects_round_trip(demo_incident: Incident) -> None:
    serde = serializer()
    hypothesis = Hypothesis(
        title="t", description="d", evidence_for=["E1"], evidence_against=[], confidence=0.4
    )
    for value in (demo_incident, hypothesis):
        restored = serde.loads_typed(serde.dumps_typed(value))
        assert restored == value
        assert type(restored) is type(value)
    assert ("agents.schemas", FinalReport.__name__) in allowed_types()
