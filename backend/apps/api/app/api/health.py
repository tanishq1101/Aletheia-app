from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection
from app.schemas.models import HealthResponse

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    """Reports real dependency state, not a hardcoded ok."""
    settings = get_settings()
    healthy = True

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        database = "ok"
    except Exception as exc:
        log.error("Health check: database unreachable: %s", exc)
        database = f"unreachable: {type(exc).__name__}"
        healthy = False

    if settings.storage_backend.lower() == "local":
        root = settings.storage_root
        try:
            root.mkdir(parents=True, exist_ok=True)
            storage = "ok" if root.is_dir() else "unwritable"
            healthy = healthy and storage == "ok"
        except OSError as exc:
            log.error("Health check: storage root unusable: %s", exc)
            storage = f"unwritable: {exc.strerror}"
            healthy = False
    else:
        storage = f"backend={settings.storage_backend} (not implemented)"
        healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if healthy else "degraded",
        database=database,
        storage=storage,
    )
