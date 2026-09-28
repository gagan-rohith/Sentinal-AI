"""Metric functions. Pure and deterministic so they can be unit tested exactly."""

import math
from collections.abc import Sequence
from statistics import mean

from pydantic import BaseModel


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Share of relevant items that appear in the top k."""
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    return sum(1 for r in set(relevant) if r in top) / len(set(relevant))


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Share of the top k that is relevant. Divides by k even when fewer were returned."""
    if k <= 0:
        raise ValueError("k must be positive")
    wanted = set(relevant)
    return sum(1 for r in retrieved[:k] if r in wanted) / k


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    wanted = set(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in wanted:
            return 1.0 / rank
    return 0.0


def brier_score(confidences: Sequence[float], correct: Sequence[bool]) -> float:
    """Mean squared error between confidence and outcome. 0 is perfect, lower is better."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and outcomes must have the same length")
    if not confidences:
        return 0.0
    return mean((c - float(o)) ** 2 for c, o in zip(confidences, correct, strict=True))


class CalibrationBin(BaseModel):
    lower: float
    upper: float
    count: int
    mean_confidence: float | None
    accuracy: float | None


def calibration_bins(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 5
) -> list[CalibrationBin]:
    result = []
    for i in range(bins):
        lower, upper = i / bins, (i + 1) / bins
        members = [
            (c, o)
            for c, o in zip(confidences, correct, strict=True)
            if lower <= c < upper or (i == bins - 1 and c == 1.0)
        ]
        result.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_confidence=round(mean(c for c, _ in members), 4) if members else None,
                accuracy=round(mean(float(o) for _, o in members), 4) if members else None,
            )
        )
    return result


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 5
) -> float:
    """Weighted gap between confidence and accuracy across bins. Lower is better."""
    total = len(confidences)
    if total == 0:
        return 0.0
    error = 0.0
    for b in calibration_bins(confidences, correct, bins):
        if b.count and b.mean_confidence is not None and b.accuracy is not None:
            error += b.count / total * abs(b.mean_confidence - b.accuracy)
    return round(error, 4)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil(pct / 100 * len(ordered)) - 1, 0)
    return ordered[index]
