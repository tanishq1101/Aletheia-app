"""Runtime-tunable settings, overriding the environment defaults.

Retrieval width, evidence count, context budget and model choice are things the
PRD commits to *measuring* (Section 3.2), which means changing them has to be
possible without a restart. Everything else — database URL, keys, storage
backend — stays in the environment where a running system cannot rewrite it.

An unset override is NULL and falls through to `.env`, so the stored row is a
patch on the configuration, never a copy of it.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection

log = get_logger(__name__)

TUNABLE_FIELDS = ("search_top_k", "rerank_top_k", "context_max_tokens", "llm_model")


@dataclass(frozen=True)
class EffectiveSettings:
    search_top_k: int
    rerank_top_k: int
    context_max_tokens: int
    llm_model: str
    # Which values came from the database rather than the environment.
    overridden: tuple[str, ...] = ()


def _stored_overrides() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT search_top_k, rerank_top_k, context_max_tokens, llm_model"
            "  FROM app_settings WHERE id = TRUE"
        )
        row = cur.fetchone()
    return {k: v for k, v in (row or {}).items() if v is not None}


def get_effective_settings() -> EffectiveSettings:
    """Environment defaults with any stored overrides applied on top."""
    env = get_settings()
    try:
        overrides = _stored_overrides()
    except Exception as exc:
        # Configuration must never be the reason a query fails; the environment
        # defaults are always a valid configuration.
        log.error("Could not read stored settings, using environment: %s", exc)
        overrides = {}

    return EffectiveSettings(
        search_top_k=overrides.get("search_top_k", env.search_top_k),
        rerank_top_k=overrides.get("rerank_top_k", env.rerank_top_k),
        context_max_tokens=overrides.get("context_max_tokens", env.context_max_tokens),
        llm_model=overrides.get("llm_model", env.openrouter_model),
        overridden=tuple(sorted(overrides)),
    )


def update_settings(values: dict) -> EffectiveSettings:
    """Store overrides. A field set to None is cleared back to the .env value."""
    fields = {k: v for k, v in values.items() if k in TUNABLE_FIELDS}
    if not fields:
        return get_effective_settings()

    assignments = ", ".join(f"{name} = %s" for name in fields)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE app_settings SET {assignments}, updated_at = now()"
                " WHERE id = TRUE",
                tuple(fields.values()),
            )
        conn.commit()

    log.info("Updated settings: %s", ", ".join(sorted(fields)))
    return get_effective_settings()


__all__ = [
    "TUNABLE_FIELDS",
    "EffectiveSettings",
    "get_effective_settings",
    "update_settings",
]
