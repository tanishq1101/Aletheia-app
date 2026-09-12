"""Cross-paper agreement matrix (PRD Phase 4).

One claim, checked against each selected paper *separately*, so a verdict can
only rest on that paper's own evidence — that separation is the whole point of
the matrix, and is why `retrieve_candidates` takes a paper filter.

Runs are bounded. Each cell is a model call, so an unbounded matrix is an
unbounded bill and a request that never returns; the caps are enforced here
rather than trusted to the UI.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.answer import get_llm_provider
from app.api.claims import run_and_store_verification
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import (
    CrossPaperMatrix,
    CrossPaperCell,
    CrossPaperRequest,
    ClaimVerification,
)
from app.services.providers import LLMProvider
from app.services.retrieval import project_exists

router = APIRouter(tags=["cross-paper"])
log = get_logger(__name__)

MAX_CLAIMS = 5
MAX_PAPERS = 5


def _load_claims(conn, project_id: UUID, claim_ids: list[UUID]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, text FROM claims
             WHERE project_id = %s AND id = ANY(%s)
             ORDER BY claim_index, created_at
            """,
            (str(project_id), [str(cid) for cid in claim_ids]),
        )
        return cur.fetchall()


def _load_papers(conn, project_id: UUID, paper_ids: list[UUID]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, filename, status FROM papers
             WHERE project_id = %s AND id = ANY(%s)
             ORDER BY created_at
            """,
            (str(project_id), [str(pid) for pid in paper_ids]),
        )
        return cur.fetchall()


def _stored_cells(conn, claim_ids: list[str], paper_ids: list[str]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, claim_id, paper_id, verdict, confidence, rationale,
                   citations, evidence_count, model, created_at
              FROM claim_verifications
             WHERE claim_id = ANY(%s) AND paper_id = ANY(%s)
            """,
            (claim_ids, paper_ids),
        )
        return cur.fetchall()


@router.post("/projects/{project_id}/cross-paper", response_model=CrossPaperMatrix)
def build_matrix(
    project_id: UUID,
    payload: CrossPaperRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> CrossPaperMatrix:
    """Check each claim against each paper, filling in any missing cells."""
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

    if len(payload.claim_ids) > MAX_CLAIMS or len(payload.paper_ids) > MAX_PAPERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A matrix is capped at {MAX_CLAIMS} claims × {MAX_PAPERS} papers; "
            f"got {len(payload.claim_ids)} × {len(payload.paper_ids)}. Each cell "
            "is a model call.",
        )

    with get_connection() as conn:
        claims = _load_claims(conn, project_id, payload.claim_ids)
        papers = _load_papers(conn, project_id, payload.paper_ids)

    if not claims or not papers:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Some of the selected claims or papers are not in this project.",
        )

    not_ready = [p for p in papers if p["status"] != "ready"]
    if not_ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(not_ready)} selected paper(s) have not finished processing.",
        )

    with get_connection() as conn:
        existing = {
            (str(row["claim_id"]), str(row["paper_id"])): row
            for row in _stored_cells(
                conn,
                [str(c["id"]) for c in claims],
                [str(p["id"]) for p in papers],
            )
        }

    cells: list[CrossPaperCell] = []
    computed = 0
    for claim in claims:
        for paper in papers:
            key = (str(claim["id"]), str(paper["id"]))
            stored = existing.get(key)

            if stored is not None and not payload.refresh:
                verification = ClaimVerification(**stored)
            else:
                verification = run_and_store_verification(
                    claim_id=claim["id"],
                    project_id=project_id,
                    claim_text=claim["text"],
                    llm=llm,
                    paper_id=paper["id"],
                )
                computed += 1

            cells.append(
                CrossPaperCell(
                    claim_id=claim["id"],
                    paper_id=paper["id"],
                    verification=verification,
                )
            )

    log.info(
        "Cross-paper matrix for project %s: %d claim(s) × %d paper(s), %d computed",
        project_id,
        len(claims),
        len(papers),
        computed,
    )
    return CrossPaperMatrix(
        claim_ids=[c["id"] for c in claims],
        paper_ids=[p["id"] for p in papers],
        cells=cells,
        cells_computed=computed,
    )


@router.get("/projects/{project_id}/cross-paper", response_model=CrossPaperMatrix)
def stored_matrix(
    project_id: UUID,
    # Query() is required for list-valued query parameters; without it FastAPI
    # reads them as a request body, which a GET never carries.
    claim_ids: list[UUID] = Query(default=[]),
    paper_ids: list[UUID] = Query(default=[]),
) -> CrossPaperMatrix:
    """Whatever has already been checked, without spending a single call."""
    if not claim_ids or not paper_ids:
        return CrossPaperMatrix(claim_ids=[], paper_ids=[], cells=[], cells_computed=0)

    with get_connection() as conn:
        rows = _stored_cells(
            conn, [str(c) for c in claim_ids], [str(p) for p in paper_ids]
        )

    return CrossPaperMatrix(
        claim_ids=claim_ids,
        paper_ids=paper_ids,
        cells=[
            CrossPaperCell(
                claim_id=row["claim_id"],
                paper_id=row["paper_id"],
                verification=ClaimVerification(**row),
            )
            for row in rows
        ],
        cells_computed=0,
    )
