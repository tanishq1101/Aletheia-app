"""Embedding providers implementing EmbeddingProvider.

Two implementations, chosen by `EMBEDDING_PROVIDER`:

* `local` (default) — fastembed / ONNX, below. No key, no spend, but ~1.4 GB
  resident once the model is loaded, which no serverless host will give us.
* `openai` / `gemini` — the hosted `/embeddings` endpoint of the same vendor
  that answers questions. This is what the Vercel deployment uses: the function
  then needs no model on disk and fits in a few hundred MB.

Both produce 512-dimensional, L2-normalised vectors, so the `vector(512)`
column and its HNSW index are shared by every mode. They are still **not**
interchangeable: each chunk records the model that embedded it, and retrieval
only compares a query against chunks from the same model (see retrieval.py).
Switching providers on a database that already holds papers therefore means
reprocessing those papers, not silently comparing two vector spaces.

Local model:

Model choice and rationale are recorded in PROGRESS.md. In short:
jinaai/jina-embeddings-v2-small-en, 512 dimensions, 8192-token context. The
long context matters — PRD Section 3.2 commits to benchmarking 600- and
800-token chunks, and a 512-token model would silently truncate two of the
three benchmark arms.

This module and `parsing.py` are the only places a heavyweight model library is
imported; everything else goes through the interfaces in `providers.py`.
"""

import math
import re
import threading
from functools import lru_cache

import httpx

from app.core.config import get_settings
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


# --- Hosted ------------------------------------------------------------------

# Both vendors expose the OpenAI `/embeddings` shape. The models are trained
# with Matryoshka representation learning, so asking for 512 dimensions (or
# truncating a longer vector to 512 and re-normalising) yields a valid
# embedding rather than a damaged one — that is what lets the hosted mode reuse
# the existing `vector(512)` schema.
HOSTED_PROFILES: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "text-embedding-3-small",
        "key_setting": "openai_api_key",
        "key_env": "OPENAI_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-embedding-001",
        "key_setting": "gemini_api_key",
        "key_env": "GEMINI_API_KEY",
    },
}


def _normalise(vector: list[float]) -> list[float]:
    vector = vector[:EMBEDDING_DIM]
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise EmbeddingError("Embedding endpoint returned a zero vector.")
    return [v / norm for v in vector]


class HostedEmbeddingProvider:
    """Implements the EmbeddingProvider protocol over an OpenAI-shaped API."""

    def __init__(
        self,
        *,
        vendor: str,
        api_key: str,
        model: str,
        base_url: str,
        key_env: str,
        timeout: float = 60.0,
    ) -> None:
        self._vendor = vendor
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._key_env = key_env
        self._timeout = timeout

    @property
    def name(self) -> str:
        # Prefixed with the vendor so the value stored on each chunk says where
        # its vector came from, not just which model family.
        return f"{self._vendor}/{self._model}"

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIM

    def embed(self, *, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key:
            raise EmbeddingError(
                f"EMBEDDING_PROVIDER={self._vendor} needs {self._key_env}. "
                "Set it in the deployment's environment."
            )
        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "input": texts,
                    "dimensions": EMBEDDING_DIM,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

        if response.status_code != 200:
            detail = response.text[:300]
            raise EmbeddingError(
                f"Embedding endpoint answered {response.status_code}: {detail}"
            )
        try:
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [_normalise(item["embedding"]) for item in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(f"Unexpected embedding response: {exc}") from exc

        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Endpoint returned {len(vectors)} vectors for {len(texts)} inputs."
            )
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingError(
                    f"Endpoint returned a {len(vector)}-dim vector; "
                    f"the schema expects {EMBEDDING_DIM}."
                )
        return vectors


# Words and individual punctuation marks, the units a WordPiece/BPE tokenizer
# never merges across.
_TOKEN_PIECES = re.compile(r"\w+|[^\w\s]")


class EstimatingTokenCounter:
    """Token budget for the hosted mode, where no tokenizer is installed.

    Counts word and punctuation pieces and scales by 1.3, the ratio measured
    for English academic prose under WordPiece/BPE. It deliberately errs high:
    an overestimate makes chunks slightly smaller than configured, while an
    underestimate could push a chunk past the embedding model's input limit.
    """

    def count(self, text: str) -> int:
        return math.ceil(len(_TOKEN_PIECES.findall(text)) * 1.3)


def embedding_mode() -> str:
    mode = get_settings().embedding_provider.strip().lower() or "local"
    if mode != "local" and mode not in HOSTED_PROFILES:
        raise EmbeddingError(
            f"Unknown EMBEDDING_PROVIDER={mode!r}; expected local, "
            + ", ".join(HOSTED_PROFILES)
            + "."
        )
    return mode


@lru_cache
def build_embedding_provider() -> FastEmbedProvider | HostedEmbeddingProvider:
    mode = embedding_mode()
    if mode == "local":
        return FastEmbedProvider()
    settings = get_settings()
    profile = HOSTED_PROFILES[mode]
    return HostedEmbeddingProvider(
        vendor=mode,
        api_key=getattr(settings, profile["key_setting"]),
        model=settings.embedding_model.strip() or profile["model"],
        base_url=settings.embedding_base_url.strip() or profile["base_url"],
        key_env=profile["key_env"],
    )


def embedding_model_name() -> str:
    """What `embedding_model` reads on chunks this deployment writes."""
    return build_embedding_provider().name


def build_token_counter() -> _ProviderTokenCounter | EstimatingTokenCounter:
    provider = build_embedding_provider()
    if isinstance(provider, FastEmbedProvider):
        return _ProviderTokenCounter(provider)
    return EstimatingTokenCounter()
