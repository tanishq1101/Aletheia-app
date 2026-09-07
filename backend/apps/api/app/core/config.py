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
    # openrouter | gemini | groq | ollama | custom. See PROVIDER_PROFILES in
    # services/llm.py; every one of them speaks the OpenAI chat shape.
    llm_provider: str = "openrouter"

    # Provider credentials. OpenRouter keeps its own settings so existing
    # deployments are unaffected. Gemini uses Google AI Studio's documented
    # variable name; base URL and model fall back to profile defaults.
    gemini_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

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

    # --- Vector store (ChromaDB) -------------------------------------------
    # Chroma is the primary index for chunk embeddings. The same vectors stay
    # mirrored in the Postgres `embedding` column, so retrieval falls back to
    # pgvector when Chroma is unreachable instead of returning nothing. That
    # fallback is also what lets the test suite run with no Chroma container.
    chroma_enabled: bool = True
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_ssl: bool = False
    # Set when pointing at a hosted Chroma that authenticates with a token.
    chroma_auth_token: str = ""
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"
    # One collection per deployment; project scoping is a metadata filter, not
    # a separate collection, so a single HNSW index serves every project.
    chroma_collection: str = "aletheia_chunks"
    # How long a single Chroma call may take before retrieval gives up on it
    # and uses pgvector. Deliberately short: a slow vector store should degrade
    # the index, not the request.
    chroma_timeout_seconds: float = 10.0

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "papers"

    github_token: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    dev_user_id: str = Field(default=DEV_USER_ID)

    # --- Authentication (Clerk) ---------------------------------------------
    # Session tokens are verified locally against Clerk's published JWKS, so
    # the secret key is not needed to authenticate a request. It is kept for
    # the Backend API calls (user lookup, revocation) that need it.
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    # Clerk session tokens have no `aud` by default. Set this only if the JWT
    # template adds one; verification is skipped while it is blank rather than
    # pretending to check a claim that is not there.
    clerk_audience: str = ""
    # Origins allowed to present a token here (the `azp` claim). Blank means
    # "do not check", which is right for a single-origin deployment and wrong
    # the moment tokens are shared between sites.
    clerk_authorized_parties_csv: str = ""

    # An API with no issuer configured refuses to start unless this says the
    # openness is deliberate. See core/auth.check_auth_configuration.
    allow_unauthenticated: bool = False

    # Per-user request budget. The LLM routes get their own, much smaller,
    # allowance: they are the ones that cost money and take seconds.
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_llm_requests_per_minute: int = 12
    rate_limit_uploads_per_hour: int = 60

    @property
    def auth_enabled(self) -> bool:
        """True when a real identity provider is configured.

        Derived rather than a flag of its own: a deployment cannot then end up
        with AUTH_ENABLED=true and no issuer, which would fail every request,
        or AUTH_ENABLED=false alongside a configured issuer, which would look
        protected and not be.
        """
        return bool(self.clerk_issuer.strip())

    @property
    def clerk_authorized_parties(self) -> list[str]:
        return [
            party.strip()
            for party in self.clerk_authorized_parties_csv.split(",")
            if party.strip()
        ]

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
