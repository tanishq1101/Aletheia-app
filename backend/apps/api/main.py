from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    agent,
    answer,
    assets,
    claims,
    conversations,
    cross_paper,
    health,
    papers,
    projects,
    reproducibility,
    search,
    settings as settings_api,
)
from app.core.auth import check_auth_configuration
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.ownership import enforce_ownership
from app.core.rate_limit import RateLimitMiddleware
from app.db.session import close_pool
from app.services.ingestion import recover_stranded_jobs

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    # Before anything is served: an API with no identity provider and no
    # explicit statement that it is meant to be open does not start.
    check_auth_configuration()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    log.info("API starting — storage=%s", settings.storage_backend)
    # Extraction runs in-process, so a job left 'running' is one a previous
    # process died holding. Fail it now so it is visible and retryable.
    recover_stranded_jobs()
    yield
    close_pool()
    log.info("API stopped")


app = FastAPI(
    title="AI Research Intelligence Platform API",
    version="0.1.0",
    description="Phase 1, Sprint 4 — ingestion, retrieval, reranking, grounded answers.",
    lifespan=lifespan,
)

# Order matters: middleware added last runs first, so the rate limiter sits
# outside CORS and sheds load before anything heavier touches the request.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers that matter for an API that also serves stored file bytes.

    `/assets/{id}/content` replays a media type recorded at ingestion. Anything
    a browser is willing to sniff into HTML there would run on the API's own
    origin, so sniffing is turned off and framing is refused outright rather
    than relying on every stored content type being trustworthy.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # Nothing served here is meant to be embedded or executed as a document.
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full trace; return something a client can act on. Never silent.
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error."}
    )


# `/health` is deliberately open: a liveness probe that needs a session is a
# liveness probe that reports the identity provider's health, not this API's.
app.include_router(health.router)

# Everything else names a resource somebody owns. The guard is attached at the
# router rather than the handler so a route added tomorrow inherits it — the
# per-handler alternative is thirty edits and one that gets forgotten.
owned = [Depends(enforce_ownership)]
app.include_router(projects.router, dependencies=owned)
app.include_router(papers.router, dependencies=owned)
app.include_router(search.router, dependencies=owned)
app.include_router(answer.router, dependencies=owned)
app.include_router(assets.router, dependencies=owned)
app.include_router(conversations.router, dependencies=owned)
app.include_router(claims.router, dependencies=owned)
app.include_router(cross_paper.router, dependencies=owned)
app.include_router(reproducibility.router, dependencies=owned)
app.include_router(agent.router, dependencies=owned)

# Settings are global and hold no user data, but writing them changes every
# caller's retrieval behaviour, so they still require a session.
app.include_router(settings_api.router, dependencies=owned)
