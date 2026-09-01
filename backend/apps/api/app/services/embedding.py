"""Local embedding provider (fastembed / ONNX) implementing EmbeddingProvider.

Model choice and rationale are recorded in PROGRESS.md. In short:
jinaai/jina-embeddings-v2-small-en, 512 dimensions, 8192-token context. The
long context matters — PRD Section 3.2 commits to benchmarking 600- and
800-token chunks, and a 512-token model would silently truncate two of the
three benchmark arms.

This module and `parsing.py` are the only places a heavyweight model library is
imported; everything else goes through the interfaces in `providers.py`.
"""

import threading
from functools import lru_cache

from app.core.logging import get_logger

log = get_logger(__name__)

MODEL_NAME = "jinaai/jina-embeddings-v2-small-en"
EMBEDDING_DIM = 512

# Loading the ONNX model takes ~25s and is not thread-safe to do twice.
_load_lock = threading.Lock()


class EmbeddingError(RuntimeError):
    """Embedding failed. Surfaced onto the job, never swallowed."""


class FastEmbedProvider:
    """Implements the EmbeddingProvider protocol."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None

    @property
    def name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIM

    def _ensure_model(self):
        if self._model is None:
            with _load_lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("Loading embedding model %s ...", self._model_name)
                    self._model = TextEmbedding(self._model_name)
                    log.info("Embedding model ready.")
        return self._model

    def embed(self, *, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Returns one L2-normalized vector per input, in order."""
        if not texts:
            return []

        try:
            model = self._ensure_model()
            vectors = [v.tolist() for v in model.embed(texts)]
        except Exception as exc:
            raise EmbeddingError(f"Embedding failed: {exc}") from exc

        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Model returned {len(vectors)} vectors for {len(texts)} inputs."
            )
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingError(
                    f"Model returned a {len(vector)}-dim vector; "
                    f"the schema expects {EMBEDDING_DIM}."
                )
        return vectors

    def count_tokens(self, text: str) -> int:
        """Token count as the embedding model itself counts.

        Uses the model's own tokenizer rather than a generic BPE: chunk budgets
        are only meaningful in the tokens this model actually sees.
        """
        model = self._ensure_model()
        tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
        if tokenizer is None:
            # fastembed internals moved. Fail loudly rather than silently
            # switching to a different, wrong token budget.
            raise EmbeddingError(
                "Could not reach the model tokenizer; token counts would be "
                "inaccurate. Check the fastembed version."
            )
        return len(tokenizer.encode(text).ids)


class _ProviderTokenCounter:
    """Adapts a provider's tokenizer to the chunker's TokenCounter protocol."""

    def __init__(self, provider: FastEmbedProvider) -> None:
        self._provider = provider

    def count(self, text: str) -> int:
        return self._provider.count_tokens(text)


@lru_cache
def build_embedding_provider() -> FastEmbedProvider:
    return FastEmbedProvider()


def build_token_counter() -> _ProviderTokenCounter:
    return _ProviderTokenCounter(build_embedding_provider())
