"""Semantic candidate retrieval — the shared first stage of search and answering.

Sprint 3 put this SQL inside the /search endpoint. Sprint 4 adds a second
consumer (answering), and PROGRESS.md is explicit that answering must **rerank
the candidate set, not re-query**. One function now owns candidate generation so
the two paths cannot drift apart.

Page and section travel with each row, so a citation resolves to
"Section 3.2, page 7" without a second query (PRD 5.2).
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.logging import get_logger
from app.db.session import get_connection
from app.services.embedding import EmbeddingError, build_embedding_provider
from app.services.vector_store import VectorStoreError
from app.services.vector_store import query as vector_query

log = get_logger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    paper_id: UUID
    paper_title: str | None
    filename: str
    content: str
    # Legitimately None for content before the first detected heading (a title
    # block, say). Citations degrade to "page N" rather than rendering "null".
    section: str | None
    chunk_index: int
    token_count: int | None
    page_number: int | None
    similarity: float


def project_exists(project_id: UUID) -> bool:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (str(project_id),))
        return cur.fetchone() is not None


def embed_query(query: str) -> list[float]:
    """Embed a query with the same model the documents used.

    Raises EmbeddingError. Comparing vectors from two different models produces
    plausible-looking garbage rather than an error, so this deliberately shares
    one provider with ingestion instead of taking a model name.
    """
    return build_embedding_provider().embed(texts=[query])[0]


def retrieve_candidates(
    *,
    project_id: UUID,
    query: str,
    top_k: int,
    paper_ids: list[UUID] | None = None,
) -> list[RetrievedChunk]:
    """Semantic top-k over a project's chunks. Raises EmbeddingError.

    `paper_ids` narrows retrieval to specific papers. Claim verification and the
    cross-paper matrix need one paper's own evidence per verdict — without the
    filter, a claim would be "verified" against a neighbouring paper's text.
    """
    query_vector = embed_query(query)

    # Chroma is the primary index. Any failure — down, timing out, empty — is
    # answered by pgvector rather than surfaced, because the same vectors live
    # in both and a degraded index should not become a degraded result.
    try:
        hits = vector_query(
            project_id=project_id,
            query_vector=query_vector,
            top_k=top_k,
            paper_ids=paper_ids,
        )
        if hits:
            rows = _hydrate(hits)
            log.info(
                "Retrieved %d candidate chunk(s) from Chroma in project %s%s for %r",
                len(rows),
                project_id,
                f" (scoped to {len(paper_ids)} paper(s))" if paper_ids else "",
                query[:60],
            )
            return rows
        log.info("Chroma returned no hits for %r — falling back to pgvector", query[:60])
    except VectorStoreError as exc:
        log.warning("Chroma retrieval unavailable (%s) — using pgvector", exc)

    return _retrieve_pgvector(
        project_id=project_id,
        query=query,
        query_vector=query_vector,
        top_k=top_k,
        paper_ids=paper_ids,
    )


def _hydrate(hits: list) -> list[RetrievedChunk]:
    """Fill Chroma's (chunk_id, similarity) pairs in from Postgres.

    Chroma indexes vectors; Postgres owns the text, section and page a citation
    is rendered from. Reading them here means the two stores cannot disagree
    about what a chunk actually says.

    Chroma's ranking is preserved: the SQL `IN` returns rows in whatever order
    the planner likes, so they are reordered against the hit list rather than
    trusted as returned.
    """
    by_id = {hit.chunk_id: hit.similarity for hit in hits}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id            AS chunk_id,
                   c.paper_id,
                   c.content,
                   c.section,
                   c.chunk_index,
                   c.token_count,
                   pg.page_number,
                   p.title         AS paper_title,
                   p.filename
              FROM paper_chunks c
              JOIN papers p       ON p.id = c.paper_id
         LEFT JOIN paper_pages pg ON pg.id = c.page_id
             WHERE c.id = ANY(%s::uuid[])
            """,
            ([str(cid) for cid in by_id],),
        )
        rows = {row["chunk_id"]: row for row in cur.fetchall()}

    hydrated: list[RetrievedChunk] = []
    for hit in hits:
        row = rows.get(hit.chunk_id)
        if row is None:
            # Indexed in Chroma but gone from Postgres — a stale vector left by
            # a delete that could not reach Chroma. Skip it and say so; serving
            # it would cite a paper that no longer exists.
            log.warning("Chunk %s is in Chroma but not in Postgres — skipped", hit.chunk_id)
            continue
        hydrated.append(RetrievedChunk(**row, similarity=hit.similarity))
    return hydrated


def _retrieve_pgvector(
    *,
    project_id: UUID,
    query: str,
    query_vector: list[float],
    top_k: int,
    paper_ids: list[UUID] | None,
) -> list[RetrievedChunk]:
    """Exact top-k straight from the `embedding` column via the HNSW index."""
    scope = [str(paper_id) for paper_id in paper_ids] if paper_ids else None

    with get_connection() as conn, conn.cursor() as cur:
        # <=> is cosine distance in pgvector; similarity is 1 - distance.
        cur.execute(
            """
            SELECT c.id            AS chunk_id,
                   c.paper_id,
                   c.content,
                   c.section,
                   c.chunk_index,
                   c.token_count,
                   pg.page_number,
                   p.title         AS paper_title,
                   p.filename,
                   1 - (c.embedding <=> %s::vector) AS similarity
              FROM paper_chunks c
              JOIN papers p       ON p.id = c.paper_id
         LEFT JOIN paper_pages pg ON pg.id = c.page_id
             WHERE p.project_id = %s
               AND c.embedding IS NOT NULL
               AND (%s::uuid[] IS NULL OR c.paper_id = ANY(%s::uuid[]))
          ORDER BY c.embedding <=> %s::vector
             LIMIT %s
            """,
            (
                str(query_vector),
                str(project_id),
                scope,
                scope,
                str(query_vector),
                top_k,
            ),
        )
        rows = cur.fetchall()

    log.info(
        "Retrieved %d candidate chunk(s) from pgvector in project %s%s for %r",
        len(rows),
        project_id,
        f" (scoped to {len(scope)} paper(s))" if scope else "",
        query[:60],
    )
    return [RetrievedChunk(**row) for row in rows]


__all__ = [
    "EmbeddingError",
    "RetrievedChunk",
    "embed_query",
    "project_exists",
    "retrieve_candidates",
]
