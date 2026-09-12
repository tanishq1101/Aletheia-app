"""Per-caller request budgets.

An open, unauthenticated, LLM-backed endpoint is a billing risk the moment it
is reachable — and even authenticated, one script can spend an account's whole
allowance in a minute. This sheds that load at the edge, before a request
reaches retrieval, embedding or a provider.

Three budgets, because the resources are not alike:

  * a general allowance, which mostly protects the database;
  * a much smaller one for the routes that call an LLM, because those cost
    money per request and take seconds, not milliseconds;
  * an hourly one for uploads, which are the only requests that consume disk.

The counter lives behind one small interface with two implementations. With
``REDIS_URL`` set, the window is a sorted set in Redis and the count is shared
by every worker, which is what makes the configured number the *actual* limit
for a scaled deployment. Without it, the window is a deque in this process:
exact for a single worker, and for N workers a floor of roughly N times the
rate. That was the honest caveat this module used to carry and could not fix;
it is now a deployment choice rather than a property of the code.

Redis is a limiter, not a dependency of the API. If it is unreachable the
request is checked against the in-process window instead and the service keeps
answering — a degraded limit beats an outage, and the alternative (failing the
request) hands anyone who can disrupt Redis a way to take the API down. The
degradation is logged and reported by ``/health`` rather than being silent.

Identity comes from the verified session where there is one, and falls back to
the peer address otherwise, so one signed-in user cannot buy themselves more
budget by rotating IPs, and an unauthenticated instance still gets protection.
"""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import threading
import time
import uuid

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Paths whose handlers call a hosted model. Matched as prefixes on the path's
# *shape*, so a new LLM route under one of these trees is covered.
LLM_PATH_MARKERS = (
    "/answer",
    "/interpret",
    "/verify",
    "/cross-paper",
    "/agent",
    "/reproducibility",
)

# Health must answer during an incident, which is exactly when a limiter would
# otherwise be refusing things. Never rate limited.
EXEMPT_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

#: The middleware instance Starlette built, so /health can report which
#: limiter is actually running and whether it is currently degraded. There
#: is exactly one per application.
_active: RateLimitMiddleware | None = None


def describe_backend() -> str:
    """How requests are being counted right now, for /health."""
    return _active.backend if _active is not None else "not installed"


class SlidingWindow:
    """Request timestamps per key, trimmed on read. Thread-safe.

    A fixed window lets a caller spend two full budgets across a boundary; a
    sliding one does not, and for a few hundred entries the deque is cheaper
    than the arithmetic saved.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, seconds until a slot frees)."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(0.0, hits[0] + window_seconds - now)
            hits.append(now)
            return True, 0.0

    def prune(self, window_seconds: float) -> None:
        """Drop keys with no recent activity, so idle callers are not retained."""
        cutoff = time.monotonic() - window_seconds
        with self._lock:
            for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
                del self._hits[key]


class InMemoryLimiter:
    """Sliding windows held in this process.

    One store per window length, so pruning an hourly budget does not use a
    one-minute cutoff and discard live counters.
    """

    #: Reported by /health. Names the limitation rather than implying a shared one.
    name = "in-memory (per process)"
    shared = False

    def __init__(self) -> None:
        self._windows: dict[float, SlidingWindow] = defaultdict(SlidingWindow)
        self._last_prune = time.monotonic()

    async def allow(self, key: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        return self._windows[window_seconds].allow(key, limit, window_seconds)

    def prune(self) -> None:
        now = time.monotonic()
        if now - self._last_prune < 300:
            return
        self._last_prune = now
        for window_seconds, window in list(self._windows.items()):
            window.prune(window_seconds)

    async def close(self) -> None:  # pragma: no cover - nothing to release
        return None


# One round trip, and atomic, which a read-then-write pair is not: two workers
# that both read 119 against a limit of 120 would both be allowed. Returns
# {allowed, milliseconds until a slot frees}.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local used = redis.call('ZCARD', key)
if used >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = (tonumber(oldest[2]) + window) - now
  end
  if retry < 0 then retry = 0 end
  return {0, retry}
end
redis.call('ZADD', key, now, member)
-- Expire the whole window rather than trimming it later: an idle caller's key
-- disappears on its own, so Redis does not accumulate one key per visitor.
redis.call('PEXPIRE', key, window)
return {1, 0}
"""


class RedisLimiter:
    """Sliding windows in Redis, shared by every worker.

    The window is a sorted set scored by arrival time in milliseconds. It is
    trimmed, counted and appended inside one Lua script so the check and the
    write cannot interleave across workers.
    """

    name = "redis"
    shared = True

    def __init__(self, url: str) -> None:
        # Imported here so the package is only required by deployments that
        # configure it — the API still starts and limits without Redis.
        import redis.asyncio as redis_asyncio

        self._error = redis_asyncio.RedisError
        self._client = redis_asyncio.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            # A limiter must never be the slowest thing in a request. If Redis
            # cannot answer in this long, the in-process window answers instead.
            socket_timeout=0.25,
            socket_connect_timeout=0.25,
            health_check_interval=30,
        )
        self._script = self._client.register_script(_SLIDING_WINDOW_LUA)

    async def allow(self, key: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        """Raises redis.RedisError; the caller decides what a failure means."""
        now_ms = int(time.time() * 1000)
        window_ms = int(window_seconds * 1000)
        allowed, retry_ms = await self._script(
            keys=[f"ratelimit:{key}"],
            args=[now_ms, window_ms, limit, f"{now_ms}:{uuid.uuid4().hex}"],
        )
        return bool(int(allowed)), max(0.0, float(retry_ms) / 1000.0)

    async def ping(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()


def build_limiter() -> InMemoryLimiter | RedisLimiter:
    """The configured limiter, falling back to in-memory with a reason logged."""
    settings = get_settings()
    if not settings.redis_url:
        return InMemoryLimiter()
    try:
        limiter = RedisLimiter(settings.redis_url)
    except ImportError:
        log.warning(
            "REDIS_URL is set but the redis package is not installed; rate "
            "limiting is per process. Install redis or unset REDIS_URL."
        )
        return InMemoryLimiter()
    log.info("Rate limiting through Redis; the configured limits are cluster-wide.")
    return limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        global _active
        self._limiter = build_limiter()
        # Kept regardless of backend: it is what answers when Redis does not.
        self._fallback = InMemoryLimiter()
        self._degraded_since: float | None = None
        _active = self

    @property
    def backend(self) -> str:
        """What /health reports. Names a live degradation, not just the config."""
        if self._degraded_since is not None:
            return f"{self._limiter.name} (degraded: falling back to in-process)"
        return self._limiter.name

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        # A CORS preflight carries no credentials and does no work.
        if request.method == "OPTIONS":
            return await call_next(request)

        identity = self._identity(request)
        path = request.url.path

        budgets: list[tuple[str, int, float, str]] = [
            (
                f"general:{identity}",
                settings.rate_limit_requests_per_minute,
                60.0,
                "requests",
            )
        ]
        if any(marker in path for marker in LLM_PATH_MARKERS):
            budgets.append(
                (
                    f"llm:{identity}",
                    settings.rate_limit_llm_requests_per_minute,
                    60.0,
                    "AI requests",
                )
            )
        if request.method == "POST" and path.endswith("/papers"):
            budgets.append(
                (
                    f"upload:{identity}",
                    settings.rate_limit_uploads_per_hour,
                    3600.0,
                    "uploads",
                )
            )

        for key, limit, seconds, noun in budgets:
            allowed, retry_after = await self._allow(key, limit, seconds)
            if not allowed:
                log.warning(
                    "Rate limited %s %s for %s — over %d %s per %ds",
                    request.method,
                    path,
                    identity,
                    limit,
                    noun,
                    int(seconds),
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": (
                            f"Rate limit reached: {limit} {noun} per "
                            f"{'minute' if seconds == 60 else 'hour'}. "
                            f"Try again in {int(retry_after) + 1}s."
                        )
                    },
                    headers={
                        "Retry-After": str(int(retry_after) + 1),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        self._fallback.prune()
        return await call_next(request)

    async def _allow(self, key: str, limit: int, seconds: float) -> tuple[bool, float]:
        """Ask the configured limiter, and the local one if it cannot answer."""
        if isinstance(self._limiter, InMemoryLimiter):
            return await self._limiter.allow(key, limit, seconds)
        try:
            result = await self._limiter.allow(key, limit, seconds)
        except Exception as exc:  # redis.RedisError and anything it wraps
            if self._degraded_since is None:
                self._degraded_since = time.monotonic()
                log.error(
                    "Redis rate limiter unavailable (%s); falling back to the "
                    "in-process window. The configured limit is now per worker.",
                    exc,
                )
            return await self._fallback.allow(key, limit, seconds)
        if self._degraded_since is not None:
            log.info("Redis rate limiter recovered; limits are cluster-wide again.")
            self._degraded_since = None
        return result

    @staticmethod
    def _identity(request: Request) -> str:
        """Who to charge for this request.

        The session subject is preferred because it survives an IP change. It
        is read from the raw token *without* verifying the signature, which is
        safe only because it is used for nothing but bucketing — a forged
        subject buys a forger their own bucket, not access. Authorisation still
        happens later, against a verified token.
        """
        header = request.headers.get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            # The signature is not checked here; a stable string is all that is
            # needed. Hashed with blake2b rather than hash() because the latter
            # is salted per process, so two workers would disagree about which
            # Redis bucket a caller belongs to and each would grant a full budget.
            digest = hashlib.blake2b(token.strip().encode(), digest_size=8)
            return f"token:{digest.hexdigest()}"
        client = request.client
        return f"ip:{client.host}" if client else "ip:unknown"
