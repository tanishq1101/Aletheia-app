"""Conversations (PRD Sprint 5).

Persistence around the Sprint 4 answering engine — no new AI logic. Answering
was stateless because `citations.message_id` is NOT NULL: a citation could not
be stored without a message to hang it on. Storing the exchange resolves that,
and makes an answer re-readable later with the evidence it was built on.
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import (
    CitationOut,
    Conversation,
    ConversationCreate,
    Message,
    MessageCreate,
    MessageExchange,
)
from app.services.answering import answer_question
from app.services.llm import LLMError
from app.services.providers import LLMProvider
from app.services.reranking import RerankError
from app.services.retrieval import EmbeddingError, project_exists

from app.api.answer import get_llm_provider

router = APIRouter(tags=["conversations"])
log = get_logger(__name__)


def _load_conversation(conn, conversation_id: UUID) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, paper_id, created_at FROM conversations"
            " WHERE id = %s",
            (str(conversation_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No conversation {conversation_id}"
        )
    return row


def _citations_for(conn, message_ids: list[str]) -> dict[str, list[CitationOut]]:
    if not message_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT message_id, paper_id, chunk_id, citation_label, support_metadata
              FROM citations
             WHERE message_id = ANY(%s)
             ORDER BY citation_label
            """,
            (message_ids,),
        )
        rows = cur.fetchall()

    grouped: dict[str, list[CitationOut]] = {}
    for row in rows:
        meta = row["support_metadata"] or {}
        grouped.setdefault(str(row["message_id"]), []).append(
            CitationOut(
                evidence_id=row["citation_label"] or "",
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
                paper_title=meta.get("paper_title"),
                page_number=meta.get("page_number"),
                section=meta.get("section"),
                location=meta.get("location", ""),
                snippet=meta.get("snippet", ""),
            )
        )
    return grouped


@router.post(
    "/projects/{project_id}/conversations",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(project_id: UUID, payload: ConversationCreate) -> Conversation:
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (project_id, paper_id)
                VALUES (%s, %s)
                RETURNING id, project_id, paper_id, created_at
                """,
                (str(project_id), str(payload.paper_id) if payload.paper_id else None),
            )
            row = cur.fetchone()
        conn.commit()

    log.info("Opened conversation %s in project %s", row["id"], project_id)
    return Conversation(**row)


@router.get(
    "/projects/{project_id}/conversations", response_model=list[Conversation]
)
def list_conversations(project_id: UUID) -> list[Conversation]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.project_id, c.paper_id, c.created_at,
                   COUNT(m.id) AS message_count,
                   MIN(m.content) FILTER (WHERE m.role = 'user') AS preview
              FROM conversations c
         LEFT JOIN messages m ON m.conversation_id = c.id
             WHERE c.project_id = %s
          GROUP BY c.id
          ORDER BY c.created_at DESC
            """,
            (str(project_id),),
        )
        return [Conversation(**row) for row in cur.fetchall()]


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message])
def list_messages(conversation_id: UUID) -> list[Message]:
    with get_connection() as conn:
        _load_conversation(conn, conversation_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, conversation_id, role, content, created_at, metadata
                  FROM messages
                 WHERE conversation_id = %s
                 ORDER BY created_at, id
                """,
                (str(conversation_id),),
            )
            rows = cur.fetchall()

        citations = _citations_for(conn, [str(row["id"]) for row in rows])

    return [
        Message(**row, citations=citations.get(str(row["id"]), [])) for row in rows
    ]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageExchange,
    status_code=status.HTTP_201_CREATED,
)
def ask(
    conversation_id: UUID,
    payload: MessageCreate,
    llm: LLMProvider = Depends(get_llm_provider),
) -> MessageExchange:
    """Ask a question in a conversation and store both turns with citations."""
    with get_connection() as conn:
        conversation = _load_conversation(conn, conversation_id)

    try:
        result = answer_question(
            project_id=conversation["project_id"],
            question=payload.query,
            llm=llm,
            top_k=payload.top_k,
            rerank_top_k=payload.rerank_top_k,
        )
    except EmbeddingError as exc:
        log.error("Could not embed question in conversation %s: %s", conversation_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not embed the question: {exc}"
        ) from exc
    except RerankError as exc:
        log.error("Reranking failed in conversation %s: %s", conversation_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not rerank evidence: {exc}"
        ) from exc
    except LLMError as exc:
        log.error("LLM call failed in conversation %s: %s", conversation_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not generate an answer: {exc}"
        ) from exc

    metadata = {
        "sufficient_evidence": result.sufficient_evidence,
        "model": result.model,
        "candidates_considered": result.candidates_considered,
        "fabricated_citations_removed": result.fabricated_citations_removed,
        "evidence_dropped_for_budget": result.evidence_dropped_for_budget,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            # clock_timestamp(), not the now() default: both turns are written
            # in one transaction, where now() is identical for both and leaves
            # the transcript ordered by a random UUID instead of by turn.
            cur.execute(
                """
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES (%s, 'user', %s, clock_timestamp())
                RETURNING id, conversation_id, role, content, created_at, metadata
                """,
                (str(conversation_id), payload.query),
            )
            user_row = cur.fetchone()

            cur.execute(
                """
                INSERT INTO messages
                    (conversation_id, role, content, metadata, created_at)
                VALUES (%s, 'assistant', %s, %s, clock_timestamp())
                RETURNING id, conversation_id, role, content, created_at, metadata
                """,
                (str(conversation_id), result.answer, json.dumps(metadata)),
            )
            assistant_row = cur.fetchone()

            for citation in result.citations:
                cur.execute(
                    """
                    INSERT INTO citations
                        (message_id, paper_id, chunk_id, citation_label,
                         support_metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(assistant_row["id"]),
                        citation.paper_id,
                        citation.chunk_id,
                        citation.evidence_id,
                        json.dumps(
                            {
                                "paper_title": citation.paper_title,
                                "page_number": citation.page_number,
                                "section": citation.section,
                                "location": citation.location,
                                "snippet": citation.snippet,
                            }
                        ),
                    ),
                )
        conn.commit()

    log.info(
        "Answered in conversation %s — %d citation(s), sufficient=%s",
        conversation_id,
        len(result.citations),
        result.sufficient_evidence,
    )
    return MessageExchange(
        user_message=Message(**user_row),
        assistant_message=Message(
            **assistant_row,
            citations=[CitationOut(**vars(c)) for c in result.citations],
        ),
    )
