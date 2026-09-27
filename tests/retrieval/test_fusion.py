import pytest

from retrieval.hybrid_search import RRF_K, reciprocal_rank_fusion, weighted_fusion


def test_rrf_scores_follow_formula() -> None:
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    assert scores["a"] == pytest.approx(1 / (RRF_K + 1))
    assert scores["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert scores["c"] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_rewards_agreement_between_rankers() -> None:
    # "b" is second in both lists; "a" and "c" are each first in only one.
    scores = reciprocal_rank_fusion([["a", "b", "x"], ["c", "b", "y"]])
    assert max(scores, key=scores.__getitem__) == "b"


def test_rrf_handles_empty_rankings() -> None:
    assert reciprocal_rank_fusion([[], []]) == {}
    assert reciprocal_rank_fusion([["a"], []]) == {"a": pytest.approx(1 / (RRF_K + 1))}


def test_weighted_fusion_normalizes_each_list() -> None:
    bm25 = {"a": 20.0, "b": 10.0}
    vector = {"a": 0.5, "b": 0.9}
    fused = weighted_fusion([bm25, vector], [0.5, 0.5])
    assert fused["a"] == pytest.approx(0.5)  # top in bm25, bottom in vector
    assert fused["b"] == pytest.approx(0.5)


def test_weighted_fusion_respects_weights() -> None:
    fused = weighted_fusion([{"a": 2.0, "b": 1.0}, {"a": 0.1, "b": 0.9}], [0.8, 0.2])
    assert fused["a"] > fused["b"]


def test_weighted_fusion_skips_empty_lists_and_single_values() -> None:
    assert weighted_fusion([{}, {"a": 0.4}], [0.5, 0.5]) == {"a": 0.0}
