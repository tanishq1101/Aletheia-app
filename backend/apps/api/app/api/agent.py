from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.answer import get_llm_provider
from app.schemas.models import (
    AgentResearchRequest,
    AgentResearchResponse,
    AgentStepResponse,
    AnswerResponse,
)
from app.services.agent import run_research_agent
from app.services.answering import AnswerResult
from app.services.llm import LLMError
from app.services.providers import LLMProvider
from app.services.retrieval import project_exists

router = APIRouter(tags=["agent"])


def _answer_response(result: AnswerResult) -> AnswerResponse:
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


@router.post(
    "/projects/{project_id}/agent/research",
    response_model=AgentResearchResponse,
)
def research_agent(
    project_id: UUID,
    payload: AgentResearchRequest,
    llm: LLMProvider = Depends(get_llm_provider),
) -> AgentResearchResponse:
    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")
    try:
        run = run_research_agent(
            project_id=project_id,
            goal=payload.goal,
            llm=llm,
            max_steps=payload.max_steps,
            synthesize=payload.synthesize, discover_sources=payload.discover_sources,
        )
    except LLMError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The research planner could not run: {exc}",
        ) from exc

    return AgentResearchResponse(
        goal=run.goal,
        planned_questions=run.plan.questions,
        planner_fallback_used=run.plan.used_fallback,
        steps=[
            AgentStepResponse(
                question=step.question,
                status=step.status,
                answer=_answer_response(step.answer) if step.answer else None,
                error=step.error,
            )
            for step in run.steps
        ],
        model=run.model,
        synthesis=_answer_response(run.synthesis) if run.synthesis else None,
        synthesis_error=run.synthesis_error, discoveries=run.discoveries,
        discovery_errors=run.discovery_errors,
    )
