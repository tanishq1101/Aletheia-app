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

The counter is a sliding window held in memory. That is a deliberate limit and
worth stating plainly: it is per process, so N workers permit roughly N times
the configured rate, and it resets on restart. For a single-process deployment
it is exactly right; for a horizontally scaled one it is a floor, not a
ceiling, and the counter belongs in Redis. It is *not* a stand-in for an
upstream WAF and does not pretend to stop a distributed flood.

Identity comes from the verified session where there is one, and falls back to
the peer address otherwise, so one signed-in user cannot buy themselves more
budget by rotating IPs, and an unauthenticated instance still gets protection.
"""

from __future__ import annotations

from collections import defaultdict, deque
import threading
import time

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._general = SlidingWindow()
        self._llm = SlidingWindow()
        self._uploads = SlidingWindow()
        self._last_prune = time.monotonic()

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        # A CORS preflight carries no credentials and does no work.
        if request.method == "OPTIONS":
            return await call_next(request)

        identity = self._identity(request)
        path = request.url.path

        budgets: list[tuple[SlidingWindow, str, int, float, str]] = [
            (
                self._general,
                f"general:{identity}",
                settings.rate_limit_requests_per_minute,
                60.0,
                "requests",
            )
        ]
        if any(marker in path for marker in LLM_PATH_MARKERS):
            budgets.append(
                (
                    self._llm,
                    f"llm:{identity}",
                    settings.rate_limit_llm_requests_per_minute,
                    60.0,
                    "AI requests",
                )
            )
        if request.method == "POST" and path.endswith("/papers"):
            budgets.append(
                (
                    self._uploads,
                    f"upload:{identity}",
                    settings.rate_limit_uploads_per_hour,
                    3600.0,
                    "uploads",
                )
            )

        for window, key, limit, seconds, noun in budgets:
            allowed, retry_after = window.allow(key, limit, seconds)
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

        self._maybe_prune()
        return await call_next(request)

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
            # needed, and hashing the token gives one without decoding it.
            return f"token:{hash(token.strip()) & 0xFFFFFFFF:08x}"
        client = request.client
        return f"ip:{client.host}" if client else "ip:unknown"

    def _maybe_prune(self) -> None:
        # Housekeeping, not on the hot path: an API with many distinct callers
        # would otherwise accumulate a deque per caller forever.
        now = time.monotonic()
        if now - self._last_prune < 300:
            return
        self._last_prune = now
        self._general.prune(60.0)
        self._llm.prune(60.0)
        self._uploads.prune(3600.0)
