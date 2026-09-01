"""Unit tests for the benchmark metrics.

These matter more than they look. The metrics are the measuring instrument for
PRD Section 12, and an instrument nobody tested produces numbers nobody should
believe. Every case here is hand-built so the expected value can be checked by
reading it, without running the pipeline.
"""

import pytest

from app.services.evaluation import (
    CitationCheck,
    LatencyBreakdown,
    MetricAccumulator,
    PageRef,
    answer_correctness,
    citation_accuracy,
    evidence_sufficiency,
    handled_unanswerable,
    hit_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    rerank_lift,
    term_matches,
    terms_missing,
    uncited_claim_ratio,
)


def refs(*pairs) -> list[PageRef]:
    return [PageRef(paper=p, page=n) for p, n in pairs]


# --- term matching -----------------------------------------------------------


def test_numeric_terms_match_on_word_boundaries():
    """The bug this rule exists to prevent: a gold term of "3" passing on "34".

    Without it, every short numeric expectation is nearly free to satisfy and
    the correctness metric quietly inflates.
    """
    assert term_matches("3", "a stack of 3 layers")
    assert not term_matches("3", "the 34-layer network")
    assert not term_matches("3", "3.57% error")


def test_decimal_terms_are_matched_exactly():
    assert term_matches("3.57", "reaching 3.57% error")
    assert not term_matches("3.5", "reaching 3.57% error")


def test_text_terms_are_case_insensitive_substrings():
    assert term_matches("Skip-gram", "the skip-gram architecture")
    assert term_matches("residual", "Residual learning eases training")


def test_empty_term_never_matches():
    assert not term_matches("", "anything at all")


def test_terms_missing_reports_only_absent_terms():
    assert terms_missing(["256", "0.9", "0.0001"], "batch 256, momentum 0.9") == [
        "0.0001"
    ]


# --- retrieval ---------------------------------------------------------------


def test_recall_counts_distinct_gold_pages_not_chunks():
    """Three chunks from one gold page is one page found, not three.

    Counting chunks would make recall climb with chunk size, which is exactly
    the variable PRD 3.2 wants the benchmark to compare.
    """
    retrieved = refs(("resnet", 4), ("resnet", 4), ("resnet", 4))
    assert recall_at_k(retrieved, {("resnet", 4), ("resnet", 7)}, k=3) == 0.5


def test_recall_at_k_respects_k():
    retrieved = refs(("bert", 1), ("bert", 2), ("bert", 3))
    gold = {("bert", 3)}
    assert recall_at_k(retrieved, gold, k=2) == 0.0
    assert recall_at_k(retrieved, gold, k=3) == 1.0


def test_recall_is_zero_when_there_is_no_gold():
    """Not 1.0. "All zero gold pages were found" is vacuously true and would
    hand unanswerable questions a perfect retrieval score."""
    assert recall_at_k(refs(("gan", 1)), set(), k=5) == 0.0
    assert hit_at_k(refs(("gan", 1)), set(), k=5) == 0.0
    assert reciprocal_rank(refs(("gan", 1)), set()) == 0.0


def test_k_larger_than_the_result_set_is_safe():
    assert recall_at_k(refs(("vgg", 2)), {("vgg", 2)}, k=100) == 1.0


def test_empty_retrieval_scores_zero():
    assert recall_at_k([], {("vgg", 2)}, k=5) == 0.0
    assert reciprocal_rank([], {("vgg", 2)}) == 0.0


def test_page_must_match_the_right_paper():
    """Page 4 of the wrong paper is not a hit. Ten papers share one project,
    so page numbers collide constantly."""
    assert recall_at_k(refs(("vgg", 4)), {("resnet", 4)}, k=1) == 0.0


def test_chunks_without_a_page_never_count_as_hits():
    assert recall_at_k([PageRef("resnet", None)], {("resnet", 4)}, k=1) == 0.0


def test_reciprocal_rank_is_one_based():
    retrieved = refs(("adam", 9), ("adam", 2), ("adam", 5))
    assert reciprocal_rank(retrieved, {("adam", 2)}) == pytest.approx(0.5)
    assert reciprocal_rank(retrieved, {("adam", 9)}) == 1.0


def test_invalid_k_scores_zero_rather_than_raising():
    assert recall_at_k(refs(("gan", 1)), {("gan", 1)}, k=0) == 0.0


def test_rerank_lift_is_measured_at_equal_k():
    """The whole point of the stage: the gold page was retrieved but ranked
    last, and reranking moved it first."""
    gold = {("rag", 6)}
    before = refs(("rag", 1), ("rag", 2), ("rag", 6))
    after = refs(("rag", 6), ("rag", 1), ("rag", 2))
    lift = rerank_lift(before=before, after=after, gold=gold, k=3)
    assert lift["recall_lift"] == 0.0  # same pages present at k=3
    assert lift["mrr_before"] == pytest.approx(1 / 3)
    assert lift["mrr_after"] == 1.0
    assert lift["mrr_lift"] == pytest.approx(2 / 3)


def test_rerank_lift_can_be_negative():
    """A metric that cannot report harm cannot report benefit either."""
    gold = {("rag", 6)}
    lift = rerank_lift(
        before=refs(("rag", 6), ("rag", 1)),
        after=refs(("rag", 1), ("rag", 6)),
        gold=gold,
        k=2,
    )
    assert lift["mrr_lift"] < 0


# --- answering ---------------------------------------------------------------


def test_answer_is_correct_only_when_every_term_is_present():
    result = answer_correctness(
        answer="They used a mini-batch size of 256 and a learning rate of 0.1.",
        must_contain=["256", "0.1"],
        must_not_contain=[],
    )
    assert result.correct
    assert result.keyword_recall == 1.0


def test_partial_credit_is_visible():
    result = answer_correctness(
        answer="They used a mini-batch size of 256.",
        must_contain=["256", "0.1"],
        must_not_contain=[],
    )
    assert not result.correct
    assert result.keyword_recall == 0.5
    assert result.missing == ["0.1"]


def test_forbidden_term_fails_even_with_every_required_term():
    result = answer_correctness(
        answer="The error was 3.57%, roughly the same as VGG.",
        must_contain=["3.57"],
        must_not_contain=["same as VGG"],
    )
    assert not result.correct
    assert result.forbidden_present == ["same as VGG"]


def test_unanswerable_is_handled_only_by_declining():
    assert handled_unanswerable(sufficient_evidence=False)
    assert not handled_unanswerable(sufficient_evidence=True)


# --- citations ---------------------------------------------------------------


def test_citation_on_a_gold_page_counts_as_precise():
    result = citation_accuracy(
        citations=[
            CitationCheck(paper="resnet", page=4, resolves=True),
            CitationCheck(paper="resnet", page=9, resolves=True),
        ],
        gold={("resnet", 4)},
        fabricated_removed=0,
    )
    assert result.precision == 0.5
    assert result.resolvable == 2
    assert result.zero_fabricated


def test_zero_fabricated_is_reported_separately_from_precision():
    """PRD 12 names 'zero fabricated citation IDs' as its own criterion. A
    fabricated ID is a grounding failure; a citation on the wrong real page is
    a retrieval failure. Collapsing them would hide which one occurred."""
    result = citation_accuracy(
        citations=[CitationCheck(paper="bert", page=3, resolves=True)],
        gold={("bert", 3)},
        fabricated_removed=2,
    )
    assert result.precision == 1.0
    assert not result.zero_fabricated
    assert result.fabricated_removed == 2


def test_no_citations_scores_zero_precision_without_dividing_by_zero():
    result = citation_accuracy(citations=[], gold={("bert", 3)}, fabricated_removed=0)
    assert result.precision == 0.0
    assert result.total == 0


def test_uncited_claim_ratio_spots_uncited_prose():
    answer = (
        "Residual learning eases the training of very deep networks in practice. "
        "The ensemble reached 3.57% top-5 error on the test set [E1]."
    )
    assert uncited_claim_ratio(answer) == 0.5


def test_short_sentences_are_not_counted_as_claims():
    assert uncited_claim_ratio("Yes. No. Maybe so.") == 0.0


def test_fully_cited_answer_has_no_uncited_claims():
    answer = "The models were trained with a mini-batch size of 256 [E2]."
    assert uncited_claim_ratio(answer) == 0.0


# --- latency -----------------------------------------------------------------


def test_percentile_is_nearest_rank():
    """Every reported latency is a real measurement, not an interpolation
    between two runs that never happened."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 50) == 30.0
    assert percentile(values, 100) == 50.0
    assert percentile(values, 1) == 10.0


def test_percentile_of_empty_sample_is_zero():
    assert percentile([], 95) == 0.0


def test_percentile_rejects_out_of_range_p():
    with pytest.raises(ValueError):
        percentile([1.0], 0)
    with pytest.raises(ValueError):
        percentile([1.0], 101)


def test_latency_breakdown_rounds_for_reporting():
    breakdown = LatencyBreakdown(
        retrieve_ms=12.345, rerank_ms=6.789, llm_ms=1000.0, total_ms=1019.134
    )
    assert breakdown.as_dict() == {
        "retrieve_ms": 12.3,
        "rerank_ms": 6.8,
        "llm_ms": 1000.0,
        "total_ms": 1019.1,
    }


def test_accumulator_mean_of_nothing_is_zero_not_an_error():
    assert MetricAccumulator("recall").mean == 0.0


def test_accumulator_tracks_mean_and_count():
    acc = MetricAccumulator("recall")
    for value in (1.0, 0.0, 0.5):
        acc.add(value)
    assert acc.count == 3
    assert acc.mean == pytest.approx(0.5)


# --- evidence sufficiency ----------------------------------------------------


def test_evidence_sufficiency_is_true_only_when_every_term_is_present():
    """The ceiling on answer correctness. Separates 'retrieval never surfaced
    the answer' from 'the model was handed the answer and did not use it' —
    two failures a bare correctness score fuses into one number."""
    evidence = "We use a weight decay of 0.0001 and a momentum of 0.9."
    assert evidence_sufficiency(
        evidence_text=evidence, must_contain=["0.0001", "0.9"]
    )
    assert not evidence_sufficiency(
        evidence_text=evidence, must_contain=["0.0001", "0.9", "256"]
    )


def test_empty_evidence_is_never_sufficient():
    assert not evidence_sufficiency(evidence_text="", must_contain=["0.9"])
