"""Vercel entrypoint: the FastAPI backend, served from the app's own domain.

The browser calls `https://<site>/api/py/<route>`; `next.config.ts` rewrites
that to this function, which strips the prefix and hands the request to the
unchanged application in `backend/apps/api`. One deployment, one origin: no
tunnel to keep alive, no CORS, and Clerk's session cookie reaches the API, so
figure images authenticate too.

A serverless function is not the long-lived process the backend was written
for, so the defaults below adjust exactly the behaviours that assume one. Each
is an ordinary setting and an explicit environment variable still wins:

  EMBEDDING_PROVIDER   hosted (the enabled LLM vendor) — no 1.4 GB ONNX model
  RERANKER_PROVIDER    none — same reason, for the cross-encoder
  INGESTION_MODE       inline — an instance may be frozen after it responds
  STORAGE_BACKEND      r2 when R2 credentials exist, otherwise postgres
  CHROMA_ENABLED       false — pgvector in the same database does retrieval
  CLERK_ISSUER         derived from NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
  STRANDED_JOB_AFTER_SECONDS  900 — never fail a live neighbour's job

Startup work (auth check, migrations, stranded-job recovery) runs on the first
request each instance serves rather than in an ASGI lifespan, because whether a
platform delivers lifespan events is not something this app should depend on.
If it fails, every route except `/health` answers 503 with the reason (health
still reports per-dependency state), and the
next request tries again.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "backend" / "apps" / "api"
sys.path.insert(0, str(API_DIR))

PREFIX = "/api/py"

# Arbitrary, fixed: one key so concurrent cold starts serialise their migrations.
_MIGRATION_LOCK_ID = 7_315_002_841

# Query parameters some providers append to their connection strings that
# libpq does not understand and refuses to connect with.
_NON_LIBPQ_PARAMS = {"supa", "pgbouncer"}


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str | None:
    """DATABASE_URL, or what Vercel's Neon / Supabase integrations inject."""
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            parts = urlsplit(value)
            query = [
                (k, v)
                for k, v in parse_qsl(parts.query)
                if k not in _NON_LIBPQ_PARAMS
            ]
            return urlunsplit(parts._replace(query=urlencode(query)))
    return None


def _clerk_issuer_from_publishable_key() -> str | None:
    """The Frontend API URL a Clerk publishable key encodes.

    `pk_test_<base64("amazed-heron-68.clerk.accounts.dev$")>` — Clerk's own SDKs
    derive the instance domain the same way. The frontend's key is already a
    project variable, so the backend can find the issuer without a second
    variable that has to be kept in step with it.
    """
    key = (
        os.environ.get("CLERK_PUBLISHABLE_KEY")
        or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
        or ""
    ).strip()
    prefix, _, encoded = key.partition("_")[2].partition("_")
    if prefix not in {"test", "live"} or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    domain = decoded.rstrip("$")
    if not domain or "/" in domain or " " in domain:
        return None
    return f"https://{domain}"


def _apply_serverless_defaults() -> None:
    url = _database_url()
    if url:
        os.environ["DATABASE_URL"] = url

    # Only one vendor's key, and neither switch set: use that vendor. With
    # OPENAI_ENABLED defaulting to true, a deployment given just a Gemini key
    # would otherwise fail every upload asking for an OpenAI key it never had.
    # Explicit switches always win.
    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    switches_set = "OPENAI_ENABLED" in os.environ or "GEMINI_ENABLED" in os.environ
    if has_gemini and not has_openai and not switches_set:
        os.environ["OPENAI_ENABLED"] = "false"
        os.environ["GEMINI_ENABLED"] = "true"

    if not os.environ.get("CLERK_ISSUER", "").strip():
        issuer = _clerk_issuer_from_publishable_key()
        if issuer:
            os.environ["CLERK_ISSUER"] = issuer

    origins = ["https://aletheia-rag.vercel.app"]
    for name in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = os.environ.get(name, "").strip()
        if host:
            origins.append(f"https://{host}")

    defaults = {
        "EMBEDDING_PROVIDER": "gemini" if _truthy("GEMINI_ENABLED") else "openai",
        "RERANKER_PROVIDER": "none",
        "INGESTION_MODE": "inline",
        "STRANDED_JOB_AFTER_SECONDS": "900",
        "CHROMA_ENABLED": "false",
        "STORAGE_BACKEND": "r2" if os.environ.get("R2_ACCESS_KEY_ID") else "postgres",
        "LOCAL_STORAGE_DIR": "/tmp/aletheia-storage",
        "RESEARCH_MODELS_DIR": str(ROOT / "backend" / "models" / "research"),
        "CORS_ORIGINS": ",".join(origins),
        "LOG_LEVEL": "INFO",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_apply_serverless_defaults()

_startup_lock = threading.Lock()
_started = False
_backend = None


def _load_backend():
    """Import the FastAPI app on first use, not at module import.

    `main` reads its settings while importing, and settings without a
    DATABASE_URL raise. Done at import time that error kills the function
    before it can answer anything; done here it becomes a 503 that says what
    is missing.
    """
    global _backend
    if _backend is None:
        from main import app

        _backend = app
    return _backend


def get_settings():
    from app.core.config import get_settings as settings

    return settings()


def _migrate() -> None:
    """Apply pending SQL migrations, the same files scripts/migrate.py runs.

    One transaction under a transaction-scoped advisory lock: that form of
    lock works through a transaction-mode pooler, and concurrent cold starts
    queue behind it instead of racing to create the same tables.
    """
    import psycopg

    files = sorted((API_DIR / "migrations").glob("*.sql"))
    with psycopg.connect(
        get_settings().database_url, prepare_threshold=None
    ) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("SELECT version FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}

        # A database built by `prisma migrate deploy` has the 0_init schema
        # (identical to SQL 0001–0011) but no rows here. Re-running 0001 on it
        # would fail on the first CREATE TABLE, so record the baseline instead.
        cur.execute("SELECT to_regclass('public.papers') IS NOT NULL")
        if not done and cur.fetchone()[0]:
            baseline = [f.stem for f in files if f.stem < "0012"]
            cur.executemany(
                "INSERT INTO schema_migrations (version) VALUES (%s)"
                " ON CONFLICT DO NOTHING",
                [(v,) for v in baseline],
            )
            done.update(baseline)

        for migration in files:
            if migration.stem not in done:
                cur.execute(migration.read_text())
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration.stem,),
                )
        conn.commit()


def _startup() -> None:
    """Once per instance, on first use. Raises with a reason a human can act on."""
    global _started
    if _started:
        return
    with _startup_lock:
        if _started:
            return
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "No database configured. Connect a Postgres database to this "
                "Vercel project (Storage → Neon) or set DATABASE_URL."
            )
        _load_backend()
        from app.core.auth import check_auth_configuration
        from app.core.logging import configure_logging
        from app.services.ingestion import recover_stranded_jobs

        configure_logging(get_settings().log_level)
        # Names only, never values: which AI settings this function can see.
        # A key added under another name, or only to Preview, shows up here.
        import logging

        visible = sorted(
            name
            for name in os.environ
            if any(t in name.upper() for t in ("OPENAI", "GEMINI", "GOOGLE", "EMBEDDING"))
        )
        logging.getLogger("vercel.entry").warning(
            "AI settings visible to this function: %s", ", ".join(visible) or "none"
        )
        check_auth_configuration()
        if os.environ.get("AUTO_MIGRATE", "true").strip().lower() != "false":
            _migrate()
        recover_stranded_jobs()
        _started = True


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        # Acknowledged, not forwarded: the backend's own lifespan would run the
        # startup checks in a place where a failure kills the whole function.
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                from app.db.session import close_pool

                close_pool()
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] in {"http", "websocket"}:
        path = scope.get("path", "")
        if path == PREFIX or path.startswith(PREFIX + "/"):
            path = path[len(PREFIX):] or "/"
            scope = {**scope, "path": path, "raw_path": path.encode()}

        if scope["type"] == "http":
            from starlette.concurrency import run_in_threadpool

            try:
                await run_in_threadpool(_startup)
            except Exception as exc:  # reported, then retried next request
                # `/health` answers regardless: it exists to describe exactly
                # this kind of broken state, database by database.
                if path == "/health" and _backend is not None:
                    await _backend(scope, receive, send)
                    return
                await _send_json(
                    send,
                    503,
                    {"detail": f"Backend is not ready: {type(exc).__name__}: {exc}"},
                )
                return

    await _load_backend()(scope, receive, send)
