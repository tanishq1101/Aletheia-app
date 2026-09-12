"""Chunk vector index — ChromaDB primary, pgvector fallback.

Every chunk embedding is written twice: to a Chroma collection, which serves
reads, and to the `paper_chunks.embedding` column, which is what search uses
when Chroma cannot answer. That is deliberate redundancy, not indecision:

  * A vector store is a cache of something the database already knows. Losing
    the container should cost latency, not results, so `search` degrades to the
    pgvector query instead of returning an empty set that looks like "no match".
  * The 270-test suite has to run with no external service. Because pgvector is
    a real path rather than a stub, the fallback is exercised on every run
    rather than being untested code that only executes during an outage.

Chroma stores vectors and the metadata needed to *filter* (project, paper), not
the metadata needed to *render* a citation. Section, page number and title are
read from Postgres afterwards, by chunk id, so the two stores cannot drift into
disagreeing about what a chunk says — Postgres stays the single source of truth
for content, and Chroma is only ever an index over it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Cosine, to match the L2-normalized vectors the embedding model emits and the
# `vector_cosine_ops` index on the Postgres side. Mixing metrics between the
# primary and the fallback would make the two paths silently rank differently.
_SPACE = "cosine"

_client: Any = None
_collection: Any = None
_lock = threading.Lock()
# Set once a connection attempt has failed, so a down Chroma costs one timeout
# rather than one per request. Cleared by `reset_vector_store`.
_unavailable_reason: str | None = None


class VectorStoreError(RuntimeError):
    """Chroma could not serve a request. Callers fall back to pgvector."""


@dataclass(frozen=True)
class VectorHit:
    """A chunk id and its similarity, before Postgres fills in the rest."""

    chunk_id: UUID
    similarity: float


def _build_client() -> Any:
    settings = get_settings()
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    headers = (
        {"Authorization": f"Bearer {settings.chroma_auth_token}"}
        if settings.chroma_auth_token
        else None
    )
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
        tenant=settings.chroma_tenant,
        database=settings.chroma_database,
        headers=headers,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection() -> Any:
    """The Chroma collection, created on first use. Raises VectorStoreError.

    Cached across requests: `HttpClient` opens a connection pool, and building
    one per call would add a handshake to every search.
    """
    global _client, _collection, _unavailable_reason

    settings = get_settings()
    if not settings.chroma_enabled:
        raise VectorStoreError("Chroma is disabled (CHROMA_ENABLED=false)")

    if _collection is not None:
        return _collection
    if _unavailable_reason is not None:
        raise VectorStoreError(_unavailable_reason)

    with _lock:
        if _collection is not None:
            return _collection
        if _unavailable_reason is not None:
            raise VectorStoreError(_unavailable_reason)
        try:
            _client = _build_client()
            _client.heartbeat()
            _collection = _client.get_or_create_collection(
                name=settings.chroma_collection,
                metadata={"hnsw:space": _SPACE},
            )
        except Exception as exc:  # noqa: BLE001 — any client error means degrade
            _unavailable_reason = f"{type(exc).__name__}: {exc}"
            _client = None
            log.warning(
                "Chroma unavailable at %s:%s (%s) — retrieval will use pgvector",
                settings.chroma_host,
                settings.chroma_port,
                _unavailable_reason,
            )
            raise VectorStoreError(_unavailable_reason) from exc
        return _collection


def reset_vector_store() -> None:
    """Drop the cached client so the next call reconnects.

    Called after a failure has been repaired, and by tests that swap config.
    """
    global _client, _collection, _unavailable_reason
    with _lock:
        _client = None
        _collection = None
        _unavailable_reason = None


def is_available() -> bool:
    """True when Chroma answered. Never raises — this is for /health."""
    try:
        get_collection()
        return True
    except VectorStoreError:
        return False


def upsert_chunks(
    *,
    project_id: UUID,
    paper_id: UUID,
    chunk_ids: list[UUID],
    vectors: list[list[float]],
    contents: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> int:
    """Mirror a paper's chunk vectors into Chroma. Raises VectorStoreError.

    Upsert rather than add, so re-processing a paper replaces its vectors
    instead of duplicating them. Returns the number of vectors written.
    """
    if not (len(chunk_ids) == len(vectors) == len(contents)):
        raise VectorStoreError(
            f"{len(chunk_ids)} ids, {len(vectors)} vectors, {len(contents)} "
            "documents — refusing to write a misaligned batch."
        )
    if not chunk_ids:
        return 0

    base = {"project_id": str(project_id), "paper_id": str(paper_id)}
    if metadatas is None:
        metadatas = [{} for _ in chunk_ids]
    merged = [{**base, **extra} for extra in metadatas]

    collection = get_collection()
    try:
        collection.upsert(
            ids=[str(cid) for cid in chunk_ids],
            embeddings=vectors,
            documents=contents,
            metadatas=merged,
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Chroma upsert failed: {exc}") from exc

    log.info("Upserted %d vector(s) into Chroma for paper %s", len(chunk_ids), paper_id)
    return len(chunk_ids)


def delete_paper(paper_id: UUID) -> None:
    """Remove a paper's vectors. Raises VectorStoreError.

    Postgres cascades on paper delete; Chroma has no foreign keys, so a paper
    removed from the database would otherwise keep answering searches.
    """
    collection = get_collection()
    try:
        collection.delete(where={"paper_id": str(paper_id)})
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Chroma delete failed: {exc}") from exc


def delete_collection() -> None:
    """Drop the whole collection. Raises VectorStoreError.

    Only correct when the embedding model changes: vectors from two models sit
    in different spaces, and mixing them degrades ranking silently rather than
    erroring. Everything is rebuildable from `paper_chunks.embedding`.
    """
    settings = get_settings()
    get_collection()  # surfaces an unreachable Chroma as VectorStoreError
    try:
        _client.delete_collection(settings.chroma_collection)
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Chroma delete_collection failed: {exc}") from exc
    reset_vector_store()


def query(
    *,
    project_id: UUID,
    query_vector: list[float],
    top_k: int,
    paper_ids: list[UUID] | None = None,
) -> list[VectorHit]:
    """Top-k chunk ids for a query vector. Raises VectorStoreError.

    Scoping is a metadata filter so one collection serves every project; a
    collection per project would fragment the HNSW graph and make cross-project
    work impossible later.
    """
    where: dict[str, Any] = {"project_id": str(project_id)}
    if paper_ids:
        # Chroma needs an explicit $and once there is more than one predicate.
        where = {
            "$and": [
                {"project_id": str(project_id)},
                {"paper_id": {"$in": [str(pid) for pid in paper_ids]}},
            ]
        }

    collection = get_collection()
    try:
        result = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where,
            include=["distances"],
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Chroma query failed: {exc}") from exc

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    if len(ids) != len(distances):
        raise VectorStoreError(
            f"Chroma returned {len(ids)} ids for {len(distances)} distances"
        )

    hits: list[VectorHit] = []
    for raw_id, distance in zip(ids, distances, strict=True):
        try:
            chunk_id = UUID(raw_id)
        except ValueError:
            # An id that is not one of ours cannot be joined back to Postgres.
            log.warning("Skipping non-UUID id %r from Chroma", raw_id)
            continue
        # Chroma reports cosine *distance*; the rest of the codebase, and the
        # API contract, speak similarity.
        hits.append(VectorHit(chunk_id=chunk_id, similarity=1.0 - float(distance)))
    return hits


def count() -> int:
    """Vectors currently indexed. Raises VectorStoreError."""
    try:
        return int(get_collection().count())
    except VectorStoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"Chroma count failed: {exc}") from exc


__all__ = [
    "VectorHit",
    "VectorStoreError",
    "count",
    "delete_collection",
    "delete_paper",
    "get_collection",
    "is_available",
    "query",
    "reset_vector_store",
    "upsert_chunks",
]
