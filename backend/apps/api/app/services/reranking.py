"""Local cross-encoder reranking (PRD 5.1 step 7), implementing RerankerProvider.

Semantic search returns ~20 plausible candidates; reranking picks the 5-8 that
actually answer the question. A bi-encoder embeds query and chunk separately, so
it can only compare two summaries; a cross-encoder reads the pair together and
is markedly better at "does this passage answer this question", which is the
judgement that matters here.

Model choice — `jinaai/jina-reranker-v1-turbo-en`, 8K context, ~150MB. The
obvious default (`Xenova/ms-marco-MiniLM-L-6-v2`) caps out at 512 tokens, and
PRD Section 3.2 benchmarks 600- and 800-token chunks: it would score two of the
three arms on partial text and still look successful. That is the same trap
Sprint 3 caught in the embedding model.

**And the model card alone was not enough.** fastembed pins *every* cross-encoder
tokenizer to `max_length=512` at load, whatever the model actually supports, so
picking an 8K model does not by itself get you 8K. Measured: with the default
cap, a passage with the answer buried at token ~700 scores *identically* to the
same passage without it (delta exactly 0.000 — the model never saw it). Lifting
the cap separates them. `_ensure_model` therefore raises the limit explicitly,
and `tests/test_reranking.py` asserts the separation so a fastembed upgrade that
re-pins it fails the suite instead of quietly degrading every ranking.

Local, like embeddings: no API key, no spend, and the real model runs in tests.
"""

import threading
from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.providers import RerankedChunk

log = get_logger(__name__)

# Loading the ONNX model is slow and not thread-safe to do twice.
_load_lock = threading.Lock()


class RerankError(RuntimeError):
    """Reranking failed. Surfaced to the caller, never swallowed."""


class FastEmbedReranker:
    """Implements the RerankerProvider protocol."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or get_settings().rerank_model
        self._model = None

    @property
    def name(self) -> str:
        return self._model_name

    def _ensure_model(self):
        if self._model is None:
            with _load_lock:
                if self._model is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    log.info("Loading reranker model %s ...", self._model_name)
                    model = TextCrossEncoder(self._model_name)
                    self._lift_truncation_cap(model)
                    self._model = model
                    log.info("Reranker ready.")
        return self._model

    def _lift_truncation_cap(self, model) -> None:
        """Raise fastembed's hardcoded 512-token cap to what the model supports.

        Left at the default, chunks longer than 512 tokens are scored on their
        first 512 tokens only — silently, with a plausible score. Failing loudly
        here is the point: a wrong ranking is far harder to notice than a
        missing model attribute.
        """
        max_tokens = get_settings().rerank_max_tokens
        # TextCrossEncoder delegates to an ONNX wrapper that owns the tokenizer.
        tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
        if tokenizer is None or not hasattr(tokenizer, "enable_truncation"):
            raise RerankError(
                "Could not reach the reranker tokenizer to lift fastembed's "
                "512-token truncation cap. Chunks above 512 tokens would be "
                "silently scored on partial text. Check the fastembed version."
            )
        tokenizer.enable_truncation(max_length=max_tokens)
        log.info("Reranker truncation cap set to %d tokens.", max_tokens)

    def rerank(
        self, *, query: str, chunks: list[tuple[str, str]], top_k: int
    ) -> list[RerankedChunk]:
        """Score (chunk_id, content) pairs against the query, best first.

        Returns at most `top_k`. Scores are cross-encoder logits: unbounded and
        **not** comparable to the cosine similarities retrieval produced. They
        are kept as a separate field everywhere downstream for that reason.
        """
        if not chunks:
            return []
        if top_k < 1:
            raise RerankError(f"top_k must be at least 1, got {top_k}")

        try:
            model = self._ensure_model()
            scores = list(model.rerank(query, [content for _, content in chunks]))
        except RerankError:
            raise  # Already carries a specific reason; re-wrapping buries it.
        except Exception as exc:
            raise RerankError(f"Reranking failed: {exc}") from exc

        if len(scores) != len(chunks):
            # A partial result would silently drop evidence from the answer.
            raise RerankError(
                f"Reranker returned {len(scores)} scores for {len(chunks)} chunks."
            )

        ranked = [
            RerankedChunk(chunk_id=chunk_id, score=float(score))
            for (chunk_id, _), score in zip(chunks, scores, strict=True)
        ]
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]


@lru_cache
def build_reranker() -> FastEmbedReranker:
    return FastEmbedReranker()
