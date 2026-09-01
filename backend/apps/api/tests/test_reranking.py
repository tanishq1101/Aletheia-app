"""Reranking tests.

Runs the real cross-encoder. Like the embedding tests, a stub would make every
assertion here vacuous — "did reranking put the relevant passage first" is the
only question worth asking, and only the real model can answer it.
"""

import pytest

from app.services.reranking import FastEmbedReranker, RerankError, build_reranker

QUERY = "How do residual connections help optimization in deep networks?"

RELEVANT = (
    "Residual connections let gradients flow through very deep networks and "
    "make optimization of hundreds of layers tractable in practice."
)
UNRELATED = (
    "Subword tokenization splits rare words into smaller units so the model "
    "vocabulary stays bounded while still covering unseen terms."
)
ALSO_UNRELATED = (
    "We report precision and recall on a held-out benchmark and compare "
    "against previously published baselines under identical conditions."
)


@pytest.fixture(scope="module")
def reranker() -> FastEmbedReranker:
    return build_reranker()


def test_relevant_chunk_outranks_unrelated_ones(reranker):
    """The whole point: reordering, not just returning k rows."""
    ranked = reranker.rerank(
        query=QUERY,
        # Deliberately supplied worst-first, so passing cannot be an accident
        # of input order.
        chunks=[("c1", UNRELATED), ("c2", ALSO_UNRELATED), ("c3", RELEVANT)],
        top_k=3,
    )

    assert [item.chunk_id for item in ranked][0] == "c3"
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_rerank_narrows_to_top_k(reranker):
    ranked = reranker.rerank(
        query=QUERY,
        chunks=[("c1", UNRELATED), ("c2", ALSO_UNRELATED), ("c3", RELEVANT)],
        top_k=1,
    )

    assert len(ranked) == 1
    assert ranked[0].chunk_id == "c3"


def test_empty_candidate_set_is_not_an_error(reranker):
    """A project with no chunks must not blow up the answering path."""
    assert reranker.rerank(query=QUERY, chunks=[], top_k=5) == []


def test_invalid_top_k_fails_loudly(reranker):
    with pytest.raises(RerankError):
        reranker.rerank(query=QUERY, chunks=[("c1", RELEVANT)], top_k=0)


def test_scoring_is_deterministic(reranker):
    """Two identical calls must agree, or nothing above is reproducible."""
    args = {"query": QUERY, "chunks": [("c1", RELEVANT)], "top_k": 1}
    assert reranker.rerank(**args)[0].score == reranker.rerank(**args)[0].score


def test_reranker_reads_past_512_tokens():
    """The reranker must see the whole chunk, not just its first 512 tokens.

    This is the Sprint 3 truncation trap in a new place. PRD Section 3.2
    benchmarks 600- and 800-token chunks, and fastembed pins EVERY cross-encoder
    tokenizer to max_length=512 at load — whatever context the model actually
    supports. Left alone, a chunk whose answer sits past token 512 is scored on
    unrelated preamble, and the score looks perfectly plausible.

    Measured before the cap was lifted: the two documents below scored
    identically to the last decimal place (delta exactly 0.000) because the
    model never saw the difference between them. If a fastembed upgrade re-pins
    the cap, this test fails instead of quietly degrading every ranking.
    """
    filler = (
        "The experimental apparatus was calibrated before each run and the "
        "ambient temperature was logged at regular intervals throughout. "
    )
    # ~840 tokens of filler, so the differing sentence lands well past 512.
    prefix = filler * 40
    buried = prefix + RELEVANT
    filler_only = prefix + filler

    ranked = build_reranker().rerank(
        query=QUERY,
        chunks=[("buried", buried), ("filler", filler_only)],
        top_k=2,
    )
    scores = {item.chunk_id: item.score for item in ranked}

    assert scores["buried"] != scores["filler"], (
        "Identical scores mean the reranker never read past the shared prefix — "
        "fastembed's 512-token truncation cap is back in force."
    )
    assert scores["buried"] > scores["filler"]


def test_reranking_beats_cosine_on_a_distractor(reranker):
    """Reranking must *correct* semantic search, not merely reshuffle it.

    This is the case that justifies the stage existing. The query asks for a
    specific number; one passage contains it and two others are about training
    and batches in general. Measured on the real models:

        passage               cosine  rank   rerank  rank
        contains the number   0.8253     3   -0.907     1
        about training        0.8323     1   -1.057     2
        about batch norm      0.8297     2   -1.865     3

    Cosine similarity puts the passage that actually answers the question
    *third* — and spreads all three across 0.007 of similarity, which is not a
    margin anything can be decided on. The cross-encoder reads query and
    passage together and puts the right one first.
    """
    query = "What batch size did the authors use to train the network?"
    answer = (
        "3.2 Implementation details. Each model is trained from scratch. We use "
        "a mini-batch size of 256 examples on eight GPUs, and the learning rate "
        "starts at 0.1 and is divided by 10 when the error plateaus."
    )
    about_training = (
        "3.1 Training setup. The networks were trained end to end by the authors "
        "using stochastic gradient descent. Training deep networks requires care, "
        "and the training procedure follows standard practice for training such "
        "architectures on large-scale data."
    )
    about_batch_norm = (
        "We adopt batch normalization right after each convolution and before "
        "activation. Batch normalization allows the network to be trained with a "
        "larger effective batch of activations per layer."
    )

    ranked = reranker.rerank(
        query=query,
        chunks=[
            ("training", about_training),
            ("batchnorm", about_batch_norm),
            ("answer", answer),
        ],
        top_k=3,
    )

    assert ranked[0].chunk_id == "answer"
