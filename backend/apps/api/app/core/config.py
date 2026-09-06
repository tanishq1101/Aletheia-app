from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]

# Sprint 1 has no auth. Seeded by migration 0002.
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    storage_backend: str = "local"
    local_storage_dir: str = "storage"
    max_upload_bytes: int = 50 * 1024 * 1024
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Chunking. PRD Section 3.2 commits to benchmarking 400 / 600 / 800 tokens,
    # so these are configuration, not constants. 600 is a mid-range starting
    # point, not a measured result.
    chunk_max_tokens: int = 600
    chunk_overlap_tokens: int = 80

    # Retrieval. PRD Section 5.1 step 7: semantic top ~20 -> rerank -> top 5-8.
    # `search_top_k` is the candidate set reranking consumes; `rerank_top_k` is
    # how many survive as evidence.
    search_top_k: int = 20
    rerank_top_k: int = 6
    # Cross-encoder, local (same rationale as the embedding model). The obvious
    # ms-marco default truncates at 512 tokens and would score 600/800-token
    # chunks on partial text; this one has 8K context. See PROGRESS.md.
    rerank_model: str = "jinaai/jina-reranker-v1-turbo-en"
    # fastembed pins every cross-encoder tokenizer to 512 tokens regardless of
    # what the model supports. This model handles 8K, so the cap is lifted
    # explicitly at load. Verified, not assumed — see tests/test_reranking.py.
    rerank_max_tokens: int = 8192

    # Experimental local classifiers enrich inspectable diagnostics only.
    research_models_enabled: bool = True
    research_models_dir: str = "models/research"

    # Context builder. The budget covers evidence text only, not the whole
    # prompt. Evidence that does not fit is dropped lowest-rank-first and
    # reported, never silently truncated.
    context_max_tokens: int = 6000

    # --- LLM (Sprint 4) -----------------------------------------------------
    # OpenRouter is OpenAI-compatible, so this provider is one HTTP call.
    # Decision and model comparison are recorded in PROGRESS.md.
    llm_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-haiku-4.5"
    # Temperature 0: grounding is constraint-following, not a creative task,
    # and a deterministic answer is one that can actually be re-verified.
    llm_temperature: float = 0.0
    llm_max_output_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    # OpenRouter's optional attribution headers.
    llm_app_title: str = "AI Research Intelligence Platform"
    llm_app_url: str = "http://localhost:3000"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "papers"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    dev_user_id: str = Field(default=DEV_USER_ID)

    @property
    def storage_root(self) -> Path:
        path = Path(self.local_storage_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    # Missing DATABASE_URL raises here rather than failing at first query.
    return Settings()
