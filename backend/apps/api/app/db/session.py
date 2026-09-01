from collections.abc import Iterator
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_settings().database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
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
