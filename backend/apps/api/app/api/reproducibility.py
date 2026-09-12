"""Reproducibility report endpoints (PRD Phase 6, disclosure scope)."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.answer import get_llm_provider
from app.api.claims import ai_error
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import (
    ReproducibilityCheck,
    ReproducibilityReport,
    ReproducibilityRequest,
)
from app.services.llm import LLMError
from app.services.providers import LLMProvider
from app.services.reranking import RerankError
from app.services.reproducibility import audit_paper
from app.services.retrieval import EmbeddingError

router = APIRouter(tags=["reproducibility"])
log = get_logger(__name__)

# Links live in the front matter and the references/appendix. Reading the whole
# document to regex it costs nothing but memory, so there is no reason to crop.
LINK_SCAN_MAX_CHARS = 400_000


def _load_paper(conn, paper_id: UUID) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, project_id, status FROM papers WHERE id = %s", (str(paper_id),)
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No paper {paper_id}")
    return row


def _paper_text(conn, paper_id: UUID) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cleaned_text FROM paper_pages WHERE paper_id = %s"
            " ORDER BY page_number",
            (str(paper_id),),
        )
        return "\n".join(row["cleaned_text"] or "" for row in cur.fetchall())[
            :LINK_SCAN_MAX_CHARS
        ]


def _load_report(conn, paper_id: UUID) -> ReproducibilityReport | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, paper_id, score, repo_metadata, links, model, created_at
              FROM reproducibility_reports
             WHERE paper_id = %s
            """,
            (str(paper_id),),
        )
        report = cur.fetchone()
        if report is None:
            return None

        cur.execute(
            """
            SELECT dimension, status, rationale, citations, check_index
              FROM reproducibility_checks
             WHERE report_id = %s
             ORDER BY check_index
            """,
            (str(report["id"]),),
        )
        checks = [ReproducibilityCheck(**row) for row in cur.fetchall()]

    return ReproducibilityReport(**report, checks=checks)


@router.get(
    "/papers/{paper_id}/reproducibility", response_model=ReproducibilityReport | None
)
def get_report(paper_id: UUID) -> ReproducibilityReport | None:
    """The stored report, or null when the paper has never been audited."""
    with get_connection() as conn:
        _load_paper(conn, paper_id)
        return _load_report(conn, paper_id)


@router.post(
    "/papers/{paper_id}/reproducibility", response_model=ReproducibilityReport
)
def run_report(
    paper_id: UUID,
    payload: ReproducibilityRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> ReproducibilityReport:
    """Audit the paper's disclosure and store the report, replacing any prior one."""
    with get_connection() as conn:
        paper = _load_paper(conn, paper_id)
        if paper["status"] != "ready":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This paper has not finished processing yet.",
            )
        text = _paper_text(conn, paper_id)

    try:
        result = audit_paper(
            project_id=paper["project_id"],
            paper_id=paper_id,
            paper_text=text,
            llm=llm,
            check_github=payload.check_github,
        )
    except EmbeddingError as exc:
        raise ai_error(exc, "Could not embed the audit queries") from exc
    except RerankError as exc:
        raise ai_error(exc, "Could not rerank evidence") from exc
    except LLMError as exc:
        raise ai_error(exc, "Could not audit the paper") from exc

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reproducibility_reports
                    (paper_id, score, repo_metadata, links, model)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (paper_id) DO UPDATE
                    SET score = EXCLUDED.score,
                        repo_metadata = EXCLUDED.repo_metadata,
                        links = EXCLUDED.links,
                        model = EXCLUDED.model,
                        created_at = now()
                RETURNING id, paper_id, score, repo_metadata, links, model, created_at
                """,
                (
                    str(paper_id),
                    result.score,
                    json.dumps(result.repo_metadata) if result.repo_metadata else None,
                    json.dumps(result.links),
                    result.model,
                ),
            )
            report = cur.fetchone()

            # The checks are the report; replacing them wholesale keeps a stale
            # dimension from surviving a re-run.
            cur.execute(
                "DELETE FROM reproducibility_checks WHERE report_id = %s",
                (str(report["id"]),),
            )
            for index, check in enumerate(result.checks):
                cur.execute(
                    """
                    INSERT INTO reproducibility_checks
                        (report_id, dimension, status, rationale, citations,
                         check_index)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(report["id"]),
                        check.label,
                        check.status,
                        check.rationale,
                        json.dumps(
                            [
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
                                for c in check.citations
                            ]
                        ),
                        index,
                    ),
                )
        conn.commit()

    with get_connection() as conn:
        stored = _load_report(conn, paper_id)

    assert stored is not None  # just written in the same request
    return stored
