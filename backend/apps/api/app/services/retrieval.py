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
    *, project_id: UUID, query: str, top_k: int
) -> list[RetrievedChunk]:
    """Semantic top-k over a project's chunks. Raises EmbeddingError."""
    query_vector = embed_query(query)

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
          ORDER BY c.embedding <=> %s::vector
             LIMIT %s
            """,
            (str(query_vector), str(project_id), str(query_vector), top_k),
        )
        rows = cur.fetchall()

    log.info(
        "Retrieved %d candidate chunk(s) in project %s for %r",
        len(rows),
        project_id,
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
