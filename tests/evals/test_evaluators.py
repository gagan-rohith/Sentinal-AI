import pytest

from evals.evaluators import (
    brier_score,
    calibration_bins,
    cosine,
    expected_calibration_error,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evals.pricing import estimate_cost


def test_recall_at_k() -> None:
    retrieved = ["a", "x", "b", "y"]
    assert recall_at_k(retrieved, ["a", "b"], 1) == 0.5
    assert recall_at_k(retrieved, ["a", "b"], 3) == 1.0
    assert recall_at_k(retrieved, ["z"], 4) == 0.0
    assert recall_at_k(retrieved, [], 3) == 0.0
    assert recall_at_k(retrieved, ["a", "a"], 1) == 1.0  # duplicates in ground truth


def test_precision_at_k_divides_by_k() -> None:
    assert precision_at_k(["a", "x", "b"], ["a", "b"], 3) == pytest.approx(2 / 3)
    assert precision_at_k(["a"], ["a"], 3) == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="positive"):
        precision_at_k(["a"], ["a"], 0)


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "y", "a"], ["a"]) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a"], ["a", "b"]) == 1.0
    assert reciprocal_rank(["x"], ["a"]) == 0.0


def test_brier_score() -> None:
    assert brier_score([1.0, 0.0], [True, False]) == 0.0
    assert brier_score([0.8, 0.4], [True, False]) == pytest.approx((0.04 + 0.16) / 2)
    assert brier_score([], []) == 0.0
    with pytest.raises(ValueError, match="same length"):
        brier_score([0.5], [])


def test_calibration_bins_and_ece() -> None:
    confidences = [0.1, 0.15, 0.9, 0.95, 1.0]
    correct = [False, False, True, True, False]
    bins = calibration_bins(confidences, correct, bins=5)
    assert [b.count for b in bins] == [2, 0, 0, 0, 3]
    assert bins[4].accuracy == pytest.approx(2 / 3, abs=1e-4)
    expected = 2 / 5 * abs(0.125 - 0) + 3 / 5 * abs(0.95 - 2 / 3)
    assert expected_calibration_error(confidences, correct, bins=5) == pytest.approx(
        expected, abs=1e-3
    )
    assert expected_calibration_error([], []) == 0.0


def test_cosine_and_percentile() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0
    assert percentile([5, 1, 3, 2, 4], 95) == 5
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([], 95) == 0.0


def test_cost_estimates() -> None:
    assert estimate_cost("claude-sonnet-5", 1_000_000, 100_000) == pytest.approx(3.0)
    assert estimate_cost(None, 0, 0) == 0.0
    assert estimate_cost("some-unknown-model", 10, 10) is None
    assert estimate_cost(None, 10, 10) is None
