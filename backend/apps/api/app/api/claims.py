"""Claim extraction and verification endpoints (PRD Phase 3)."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.answer import get_llm_provider
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import (
    Claim,
    ClaimCreate,
    ClaimVerification,
    ClaimWithVerification,
    ExtractClaimsRequest,
)
from app.services.llm import LLMError
from app.services.providers import LLMProvider
from app.services.reranking import RerankError
from app.services.retrieval import EmbeddingError, project_exists
from app.services.verification import extract_claims, verify_claim

router = APIRouter(tags=["claims"])
log = get_logger(__name__)

# How much of a paper the claim extractor reads. The abstract and conclusion
# carry the paper's own claims; feeding the whole document costs more and
# returns method detail rather than assertions.
EXTRACTION_MAX_CHARS = 12000


def ai_error(exc: Exception, action: str) -> HTTPException:
    """Every AI failure reaches the client with its real reason (PRD §9)."""
    log.error("%s failed: %s", action, exc)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{action}: {exc}")


def _load_paper(conn, paper_id: UUID) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, title, filename, status, abstract"
            "  FROM papers WHERE id = %s",
            (str(paper_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")
    return row


def _claim_source_text(conn, paper: dict) -> str:
    """The paper's own summary of what it found: abstract plus conclusions."""
    parts: list[str] = []
    if paper["abstract"]:
        parts.append(paper["abstract"])

    with conn.cursor() as cur:
        # Conclusion-ish sections state results as claims; the rest of the body
        # mostly describes method.
        cur.execute(
            """
            SELECT content
              FROM paper_chunks
             WHERE paper_id = %s
               AND (section ILIKE '%%conclusion%%'
                 OR section ILIKE '%%result%%'
                 OR section ILIKE '%%discussion%%'
                 OR section ILIKE '%%abstract%%')
             ORDER BY chunk_index
            """,
            (str(paper["id"]),),
        )
        parts.extend(row["content"] for row in cur.fetchall())

        if len(parts) <= 1:
            # No recognisable results sections — fall back to the opening of
            # the paper rather than extracting from nothing.
            cur.execute(
                "SELECT content FROM paper_chunks WHERE paper_id = %s"
                " ORDER BY chunk_index LIMIT 6",
                (str(paper["id"]),),
            )
            parts.extend(row["content"] for row in cur.fetchall())

    return "\n\n".join(parts)[:EXTRACTION_MAX_CHARS]


def _verifications_for(conn, claim_ids: list[str]) -> dict[str, ClaimVerification]:
    """The current project-wide verdict per claim.

    `paper_id IS NULL` is the filter that matters: the cross-paper matrix
    stores a second verdict per claim for every paper it was checked against,
    and one of those must never be shown as the claim's overall verdict.
    """
    if not claim_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, claim_id, paper_id, verdict, confidence, rationale,
                   citations, evidence_count, model, created_at
              FROM claim_verifications
             WHERE claim_id = ANY(%s)
               AND paper_id IS NULL
            """,
            (claim_ids,),
        )
        return {
            str(row["claim_id"]): ClaimVerification(**row) for row in cur.fetchall()
        }


@router.post(
    "/papers/{paper_id}/claims/extract",
    response_model=list[Claim],
    status_code=status.HTTP_201_CREATED,
)
def extract_paper_claims(
    paper_id: UUID,
    payload: ExtractClaimsRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> list[Claim]:
    """Extract the checkable claims a paper makes, replacing any previous set."""
    with get_connection() as conn:
        paper = _load_paper(conn, paper_id)
        if paper["status"] != "ready":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This paper has not finished processing yet.",
            )
        text = _claim_source_text(conn, paper)

    if not text.strip():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No extracted text is available for this paper.",
        )

    try:
        claims = extract_claims(text=text, llm=llm, limit=payload.limit)
    except LLMError as exc:
        raise ai_error(exc, "Could not extract claims") from exc

    if not claims:
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Re-extracting replaces the previous set; verdicts cascade with
            # their claims, since a verdict on a deleted claim means nothing.
            cur.execute(
                "DELETE FROM claims WHERE paper_id = %s AND source = 'extracted'",
                (str(paper_id),),
            )
            rows = []
            for index, text_line in enumerate(claims):
                cur.execute(
                    """
                    INSERT INTO claims
                        (project_id, paper_id, text, source, claim_index)
                    VALUES (%s, %s, %s, 'extracted', %s)
                    RETURNING id, project_id, paper_id, text, source, claim_index,
                              created_at
                    """,
                    (str(paper["project_id"]), str(paper_id), text_line, index),
                )
                rows.append(cur.fetchone())
        conn.commit()

    log.info("Extracted %d claim(s) from paper %s", len(rows), paper_id)
    return [Claim(**row) for row in rows]


@router.get("/papers/{paper_id}/claims", response_model=list[ClaimWithVerification])
def list_paper_claims(paper_id: UUID) -> list[ClaimWithVerification]:
    with get_connection() as conn:
        _load_paper(conn, paper_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, paper_id, text, source, claim_index,
                       created_at
                  FROM claims
                 WHERE paper_id = %s
                 ORDER BY claim_index, created_at
                """,
                (str(paper_id),),
            )
            rows = cur.fetchall()

        verdicts = _verifications_for(conn, [str(row["id"]) for row in rows])

    return [
        ClaimWithVerification(**row, verification=verdicts.get(str(row["id"])))
        for row in rows
    ]


@router.post(
    "/projects/{project_id}/claims",
    response_model=Claim,
    status_code=status.HTTP_201_CREATED,
)
def create_claim(project_id: UUID, payload: ClaimCreate) -> Claim:
    """Record a claim the user typed, for checking against the project."""
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claims (project_id, paper_id, text, source)
                VALUES (%s, %s, %s, 'manual')
                RETURNING id, project_id, paper_id, text, source, claim_index,
                          created_at
                """,
                (
                    str(project_id),
                    str(payload.paper_id) if payload.paper_id else None,
                    payload.text.strip(),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return Claim(**row)


@router.get("/projects/{project_id}/claims", response_model=list[ClaimWithVerification])
def list_project_claims(project_id: UUID) -> list[ClaimWithVerification]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, paper_id, text, source, claim_index,
                       created_at
                  FROM claims
                 WHERE project_id = %s
                 ORDER BY created_at DESC
                """,
                (str(project_id),),
            )
            rows = cur.fetchall()
        verdicts = _verifications_for(conn, [str(row["id"]) for row in rows])

    return [
        ClaimWithVerification(**row, verification=verdicts.get(str(row["id"])))
        for row in rows
    ]


def run_and_store_verification(
    *,
    claim_id: UUID,
    project_id: UUID,
    claim_text: str,
    llm: LLMProvider,
    paper_id: UUID | None,
) -> ClaimVerification:
    """Verify one claim and persist the verdict, replacing any previous one."""
    try:
        verdict = verify_claim(
            project_id=project_id,
            claim=claim_text,
            llm=llm,
            paper_ids=[paper_id] if paper_id else None,
        )
    except EmbeddingError as exc:
        raise ai_error(exc, "Could not embed the claim") from exc
    except RerankError as exc:
        raise ai_error(exc, "Could not rerank evidence") from exc
    except LLMError as exc:
        raise ai_error(exc, "Could not verify the claim") from exc

    citations = [
        {
            "evidence_id": c.evidence_id,
            "chunk_id": str(c.chunk_id),
            "paper_id": str(c.paper_id),
            "paper_title": c.paper_title,
            "page_number": c.page_number,
            "section": c.section,
            "location": c.location,
            "snippet": c.snippet,
        }
        for c in verdict.citations
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claim_verifications
                    (claim_id, paper_id, verdict, confidence, rationale,
                     citations, evidence_count, model)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (claim_id,
                             COALESCE(paper_id,
                                      '00000000-0000-0000-0000-000000000000'::uuid))
                DO UPDATE SET verdict = EXCLUDED.verdict,
                              confidence = EXCLUDED.confidence,
                              rationale = EXCLUDED.rationale,
                              citations = EXCLUDED.citations,
                              evidence_count = EXCLUDED.evidence_count,
                              model = EXCLUDED.model,
                              created_at = now()
                RETURNING id, claim_id, paper_id, verdict, confidence, rationale,
                          citations, evidence_count, model, created_at
                """,
                (
                    str(claim_id),
                    str(paper_id) if paper_id else None,
                    verdict.verdict,
                    verdict.confidence,
                    verdict.rationale,
                    json.dumps(citations),
                    verdict.evidence_count,
                    verdict.model,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return ClaimVerification(**row)


@router.post("/claims/{claim_id}/verify", response_model=ClaimVerification)
def verify(
    claim_id: UUID,
    llm: LLMProvider = Depends(get_llm_provider),
) -> ClaimVerification:
    """Check a stored claim against every paper in its project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, text FROM claims WHERE id = %s", (str(claim_id),)
        )
        claim = cur.fetchone()
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No claim {claim_id}")

    return run_and_store_verification(
        claim_id=claim["id"],
        project_id=claim["project_id"],
        claim_text=claim["text"],
        llm=llm,
        paper_id=None,
    )
