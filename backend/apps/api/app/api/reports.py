"""PDF export for the grounded surfaces (Ask, Research Agent, Reproducibility).

These endpoints render a result the caller already holds. They do not call the
model, do not read the library, and cost nothing but CPU — which is also why
their paths avoid the `LLM_PATH_MARKERS` substrings in `core/rate_limit.py`:
downloading a report you have already paid for must not consume the much
smaller AI request budget.

Taking the result as the request body is deliberate rather than convenient. The
models this ships against refuse `temperature=0` and do not reproduce their own
answers, so an endpoint that re-ran the question would hand back a *different*
document from the one on screen while calling it the same report. Ownership of
the surrounding project or paper is still enforced by the path id, as for every
other route.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.core.logging import get_logger
from app.schemas.models import (
    AgentReportRequest,
    AnswerReportRequest,
    ReproducibilityReportRequest,
)
from app.services import report as report_service
from app.services.pdf import render_pdf
from app.services.report import ReportDocument
from app.services.retrieval import project_exists

router = APIRouter(tags=["reports"])
log = get_logger(__name__)


def _pdf(document: ReportDocument) -> Response:
    """Render, or fail with a reason rather than a blank download."""
    try:
        body = render_pdf(document)
    except Exception as exc:
        # A report that cannot be drawn must say so. A 200 carrying a broken
        # PDF is worse than an error: the browser saves it and the reader
        # discovers the problem later, without the context to report it.
        log.exception("Could not render %s", document.filename)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"The report could not be rendered as a PDF: "
            f"{type(exc).__name__}: {exc}",
        ) from exc

    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{document.filename}"',
            # The filename is generated from the goal, so it is not secret —
            # but it is user text, and a cache shared between users should not
            # keep a document built from one person's library.
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/projects/{project_id}/reports/ask.pdf")
def answer_report(project_id: UUID, payload: AnswerReportRequest) -> Response:
    """One grounded answer, with every cited passage reproduced."""
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")
    return _pdf(report_service.answer_document(
        question=payload.question,
        answer=payload.answer,
        project_name=payload.project_name,
    ))


@router.post("/projects/{project_id}/reports/brief.pdf")
def agent_report(project_id: UUID, payload: AgentReportRequest) -> Response:
    """A complete research brief: the finding, every question, every passage."""
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")
    return _pdf(report_service.agent_document(
        run=payload.run, project_name=payload.project_name,
    ))


@router.post("/papers/{paper_id}/reports/disclosure.pdf")
def reproducibility_report(
    paper_id: UUID, payload: ReproducibilityReportRequest
) -> Response:
    """A paper's reproducibility disclosure audit."""
    if payload.report.paper_id != paper_id:
        # The path id is what ownership was checked against, so a body naming a
        # different paper must not be rendered under it.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The report in the request body belongs to a different paper.",
        )
    return _pdf(report_service.reproducibility_document(
        report=payload.report, paper_title=payload.paper_title,
    ))
