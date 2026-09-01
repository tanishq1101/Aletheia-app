from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.models import SearchRequest, SearchResult
from app.services.retrieval import (
    EmbeddingError,
    project_exists,
    retrieve_candidates,
)

router = APIRouter(tags=["search"])
log = get_logger(__name__)


@router.post("/projects/{project_id}/search", response_model=list[SearchResult])
def search(project_id: UUID, payload: SearchRequest) -> list[SearchResult]:
    """Semantic retrieval over a project's chunks.

    This is the raw candidate set (PRD 5.1 step 7, before reranking). It stays
    exposed on its own because retrieval quality has to be inspectable
    independently of answer quality — Sprint 6 measures the two separately.
    For reranked evidence and a grounded answer, use /projects/{id}/answer.
    """
    settings = get_settings()
    top_k = payload.top_k or settings.search_top_k

    if not project_exists(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project {project_id}")

    try:
        candidates = retrieve_candidates(
            project_id=project_id, query=payload.query, top_k=top_k
        )
    except EmbeddingError as exc:
        log.error("Could not embed query for project %s: %s", project_id, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not embed the query: {exc}"
        ) from exc

    return [SearchResult(**vars(chunk)) for chunk in candidates]
