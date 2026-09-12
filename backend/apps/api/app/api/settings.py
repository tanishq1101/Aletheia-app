"""Runtime configuration endpoints.

What is deliberately absent: the API key. The settings page needs to know
whether answering is configured, which is a boolean; the key itself has no
business leaving the process (PRD Section 9 — secrets stay in the environment).
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.models import SettingsResponse, SettingsUpdate
from app.services.embedding import MODEL_NAME as EMBEDDING_MODEL
from app.services.settings_store import get_effective_settings, update_settings

router = APIRouter(tags=["settings"])
log = get_logger(__name__)


def _current() -> SettingsResponse:
    env = get_settings()
    effective = get_effective_settings()

    return SettingsResponse(
        search_top_k=effective.search_top_k,
        rerank_top_k=effective.rerank_top_k,
        context_max_tokens=effective.context_max_tokens,
        llm_model=effective.llm_model,
        llm_provider=env.llm_provider,
        # Whether answering can work at all — never the key itself.
        llm_key_configured=bool(
            (env.openai_api_key or env.gemini_api_key)
            if env.llm_provider == "openai"
            else env.openrouter_api_key
            if env.llm_provider == "openrouter"
            else env.gemini_api_key
            if env.llm_provider == "gemini"
            else env.llm_api_key
        ),
        embedding_model=EMBEDDING_MODEL,
        rerank_model=env.rerank_model,
        chunk_max_tokens=env.chunk_max_tokens,
        chunk_overlap_tokens=env.chunk_overlap_tokens,
        storage_backend=env.storage_backend,
        max_upload_bytes=env.max_upload_bytes,
        github_token_configured=bool(env.github_token),
        dev_user_id=env.dev_user_id,
        overridden=list(effective.overridden),
    )


@router.get("/settings", response_model=SettingsResponse)
def read_settings() -> SettingsResponse:
    """The configuration actually in force, environment plus overrides."""
    return _current()


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(payload: SettingsUpdate) -> SettingsResponse:
    """Change a tunable. Omitted fields are left alone; null clears an override."""
    update_settings(payload.model_dump(exclude_unset=True))
    return _current()
