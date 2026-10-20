from collections.abc import Iterator
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_pool: ConnectionPool | None = None


def _is_pooled(url: str) -> bool:
    return "-pooler." in url or ":6543/" in url or "pgbouncer=true" in url


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = get_settings().database_url
        _pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=10,
            kwargs={
                "row_factory": dict_row,
                # Server-side prepared statements do not survive a
                # transaction-mode pooler (Neon's "-pooler" host, Supabase's
                # port 6543): the next transaction can land on a backend that
                # never saw the PREPARE. Off there, psycopg's default elsewhere.
                **({"prepare_threshold": None} if _is_pooled(url) else {}),
            },
            # Without this the pool hands out connections killed by a database
            # restart, and every request fails for ~20s until its background
            # worker notices. Costs one round-trip per checkout.
            check=ConnectionPool.check_connection,
            open=True,
        )
    return _pool


@contextmanager
def get_connection() -> Iterator:
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
