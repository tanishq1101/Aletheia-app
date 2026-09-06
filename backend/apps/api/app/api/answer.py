"""Grounded answering endpoint (PRD Sprint 4).

Stateless by design: nothing is written to `conversations`, `messages`, or
`citations`. PRD Section 7 makes `citations.message_id` a NOT NULL foreign key,
so persisting a citation requires a message row — and conversations are a
Sprint 5 deliverable. Citation *resolution* is fully delivered here; only its
persistence waits. Decision recorded in PROGRESS.md.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging import get_logger
from app.schemas.models import AnswerRequest, AnswerResponse
from app.services.answering import answer_question
from app.services.llm import LLMConfigurationError, LLMError, build_llm_provider
from app.services.providers import LLMProvider
from app.services.reranking import RerankError
from app.services.retrieval import EmbeddingError, project_exists

router = APIRouter(tags=["answer"])
log = get_logger(__name__)


def get_llm_provider() -> LLMProvider:
    """LLM as a dependency so tests can substitute a scripted provider.

    Grounding, citation validation, and resolution are provider-independent, so
    they are worth testing without a network call or a bill. Overriding here
    swaps the model and nothing else — no monkeypatching of module internals.
    """
    try:
        return build_llm_provider()
    except LLMConfigurationError as exc:
        # A missing key is a deployment problem, not a bad request.
        log.error("LLM provider is not configured: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/projects/{project_id}/answer", response_model=AnswerResponse)
def answer(
    project_id: UUID,
    payload: AnswerRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> AnswerResponse:
    """Answer a question from a project's papers, grounded in cited evidence."""
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

    try:
        result = answer_question(
            project_id=project_id,
            question=payload.query,
            llm=llm,
            top_k=payload.top_k,
            rerank_top_k=payload.rerank_top_k,
        )
    except EmbeddingError as exc:
        log.error("Could not embed question for project %s: %s", project_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not embed the question: {exc}"
        ) from exc
    except RerankError as exc:
        log.error("Reranking failed for project %s: %s", project_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not rerank evidence: {exc}"
        ) from exc
    except LLMError as exc:
        # The provider's own reason travels with it — "answering failed" alone
        # is not diagnosable (PRD Section 9).
        log.error("LLM call failed for project %s: %s", project_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not generate an answer: {exc}"
        ) from exc

    return AnswerResponse(
        answer=result.answer,
        sufficient_evidence=result.sufficient_evidence,
        citations=[vars(citation) for citation in result.citations],
        evidence=[
            {
                "evidence_id": item.evidence_id,
                "chunk_id": item.chunk_id,
                "paper_id": item.paper_id,
                "paper_title": item.paper_title,
                "page_number": item.page_number,
                "section": item.section,
                "location": item.location,
                "content": item.content,
                "similarity": item.similarity,
                "rerank_score": item.rerank_score,
                "source_url": item.source_url,
            }
            for item in result.evidence
        ],
        fabricated_citations_removed=result.fabricated_citations_removed,
        candidates_considered=result.candidates_considered,
        evidence_dropped_for_budget=result.evidence_dropped_for_budget,
        model=result.model,
        model_diagnostics=result.model_diagnostics,
        charts=result.charts,
        truncated=result.truncated,
    )
