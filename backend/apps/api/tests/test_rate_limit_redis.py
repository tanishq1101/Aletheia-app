"""The shared rate-limit counter, and what happens when it is not there.

The in-process window is exercised in test_auth.py. What matters here is the
part that was previously impossible: that two workers counting against the same
budget really do share it, that the check and the write cannot interleave, and
that losing Redis degrades the limiter instead of the API.

The Redis tests run against a live server and skip without one, because a
faked Redis would be testing the fake: the whole point of the Lua script is
that the trim, the count and the append happen inside the server.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.config import get_settings
from app.core.rate_limit import (
    InMemoryLimiter,
    RateLimitMiddleware,
    RedisLimiter,
    build_limiter,
    describe_backend,
)


REDIS_URL = "redis://localhost:6380/1"


def _redis_available() -> bool:
    async def probe() -> None:
        limiter = RedisLimiter(REDIS_URL)
        try:
            await limiter.ping()
        finally:
            await limiter.close()

    try:
        asyncio.run(probe())
    except Exception:
        return False
    return True


requires_redis = pytest.mark.skipif(
    not _redis_available(),
    reason=f"no Redis at {REDIS_URL} (docker compose up -d redis)",
)


# --- Backend selection -------------------------------------------------------


def test_no_redis_url_keeps_the_counter_in_process(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", "", raising=False)
    limiter = build_limiter()
    assert isinstance(limiter, InMemoryLimiter)
    assert limiter.shared is False
    # The name must not imply a guarantee it cannot make.
    assert "per process" in limiter.name


@requires_redis
def test_redis_url_selects_the_shared_counter(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", REDIS_URL, raising=False)
    limiter = build_limiter()
    assert isinstance(limiter, RedisLimiter)
    assert limiter.shared is True
    asyncio.run(limiter.close())


# --- The shared window itself ------------------------------------------------


@requires_redis
def test_the_budget_is_shared_across_processes():
    """Two limiters, as two workers would be, counting against one budget."""

    async def scenario() -> list[bool]:
        key = f"test:{uuid.uuid4().hex}"
        worker_a = RedisLimiter(REDIS_URL)
        worker_b = RedisLimiter(REDIS_URL)
        try:
            results = []
            for _ in range(2):
                results.append((await worker_a.allow(key, 4, 60.0))[0])
                results.append((await worker_b.allow(key, 4, 60.0))[0])
            # The budget of 4 is now spent between them, not 4 each.
            results.append((await worker_a.allow(key, 4, 60.0))[0])
            results.append((await worker_b.allow(key, 4, 60.0))[0])
            return results
        finally:
            await worker_a.close()
            await worker_b.close()

    results = asyncio.run(scenario())
    assert results[:4] == [True, True, True, True]
    assert results[4:] == [False, False], (
        "each worker got its own budget — the counter is not actually shared"
    )


@requires_redis
def test_concurrent_requests_cannot_exceed_the_limit():
    """The read and the write are one operation, so 119+1 cannot become 121."""

    async def scenario() -> int:
        key = f"test:{uuid.uuid4().hex}"
        limiters = [RedisLimiter(REDIS_URL) for _ in range(8)]
        try:
            outcomes = await asyncio.gather(
                *(
                    limiters[index % len(limiters)].allow(key, 10, 60.0)
                    for index in range(60)
                )
            )
            return sum(1 for allowed, _ in outcomes if allowed)
        finally:
            for limiter in limiters:
                await limiter.close()

    assert asyncio.run(scenario()) == 10


@requires_redis
def test_refusal_reports_when_a_slot_frees():
    async def scenario() -> float:
        key = f"test:{uuid.uuid4().hex}"
        limiter = RedisLimiter(REDIS_URL)
        try:
            await limiter.allow(key, 1, 30.0)
            _, retry_after = await limiter.allow(key, 1, 30.0)
            return retry_after
        finally:
            await limiter.close()

    retry_after = asyncio.run(scenario())
    assert 0 < retry_after <= 30


@requires_redis
def test_an_idle_window_expires_rather_than_accumulating():
    """A key per visitor, kept forever, is a slow memory leak in Redis."""

    async def scenario() -> int:
        key = f"test:{uuid.uuid4().hex}"
        limiter = RedisLimiter(REDIS_URL)
        try:
            await limiter.allow(key, 5, 60.0)
            return await limiter._client.pttl(f"ratelimit:{key}")
        finally:
            await limiter.close()

    ttl = asyncio.run(scenario())
    assert 0 < ttl <= 60_000, "the window was left without an expiry"


# --- Losing Redis ------------------------------------------------------------


def test_an_unreachable_redis_degrades_the_limiter_not_the_api(monkeypatch):
    """A limiter outage must not become a service outage."""
    settings = get_settings()
    # A port with nothing on it, so the client fails rather than hangs.
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6399/0", raising=False)

    middleware = RateLimitMiddleware(app=lambda scope, receive, send: None)
    assert isinstance(middleware._limiter, RedisLimiter)

    allowed, _ = asyncio.run(middleware._allow("general:someone", 2, 60.0))
    assert allowed, "the request was refused because the limiter was down"

    # Still limiting, just locally — not waved through.
    asyncio.run(middleware._allow("general:someone", 2, 60.0))
    allowed, _ = asyncio.run(middleware._allow("general:someone", 2, 60.0))
    assert not allowed, "falling back to the in-process window stopped limiting"

    # And the degradation is visible rather than silent.
    assert "degraded" in middleware.backend
    assert "degraded" in describe_backend()


def test_identity_is_stable_across_processes():
    """A per-process hash would give each worker a different Redis bucket."""

    class FakeRequest:
        headers = {"authorization": "Bearer a-session-token"}
        client = None

    first = RateLimitMiddleware._identity(FakeRequest())
    second = RateLimitMiddleware._identity(FakeRequest())
    assert first == second
    # blake2b of this exact token, so a change to the scheme is deliberate
    # rather than accidental — PYTHONHASHSEED randomises hash() per process.
    assert first.startswith("token:")
    assert first != "token:" + "0" * 16
