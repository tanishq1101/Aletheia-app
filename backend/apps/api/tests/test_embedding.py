"""Embedding provider contract tests.

These load the real model (cached after first use) — the point is to verify the
actual provider, not a stub.
"""

import math

import pytest

from app.services.embedding import (
    EMBEDDING_DIM,
    EmbeddingError,
    build_embedding_provider,
    build_token_counter,
)


@pytest.fixture(scope="module")
def provider():
    return build_embedding_provider()


def test_reports_its_dimensionality_and_name(provider):
    assert provider.dimensions == EMBEDDING_DIM
    assert "jina" in provider.name


def test_embeds_a_batch_in_order(provider):
    texts = ["residual networks", "convolutional layers", "banana bread recipe"]

    vectors = provider.embed(texts=texts)

    assert len(vectors) == 3
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    # Same input must give the same vector — retrieval depends on it.
    assert provider.embed(texts=[texts[0]])[0] == pytest.approx(vectors[0])


def test_vectors_are_l2_normalized(provider):
    """Cosine indexing assumes unit vectors."""
    [vector] = provider.embed(texts=["deep residual learning"])

    assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1.0, abs=1e-3)


def test_related_text_scores_higher_than_unrelated(provider):
    query, related, unrelated = provider.embed(
        texts=[
            "How do residual connections help train deep networks?",
            "Residual connections ease optimization in very deep neural networks.",
            "Sourdough starter needs regular feeding with flour and water.",
        ]
    )

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosine(query, related) > cosine(query, unrelated)


def test_empty_batch_is_a_no_op(provider):
    assert provider.embed(texts=[]) == []


def test_token_counter_matches_the_model_tokenizer():
    counter = build_token_counter()

    assert counter.count("") == 2  # [CLS] and [SEP] alone
    short = counter.count("residual learning")
    longer = counter.count("residual learning eases the training of deep networks")
    assert 0 < short < longer


def test_token_counter_is_not_a_word_count():
    """Subword tokenization must be reflected, or chunk budgets are wrong."""
    counter = build_token_counter()

    # A word the tokenizer must split into multiple subwords.
    assert counter.count("unbelievability") > 3


def test_embedding_error_is_raised_not_swallowed(provider, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(provider, "_ensure_model", boom)

    with pytest.raises(EmbeddingError):
        provider.embed(texts=["anything"])
