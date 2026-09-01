#!/usr/bin/env python3
"""Apply numbered SQL migrations in order, skipping ones already applied.

Plain SQL on purpose (see PROGRESS.md): the Supabase CLI consumes this same
format, so moving off local Postgres is a file move rather than a rewrite.

    python scripts/migrate.py [--status]
"""

import argparse
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "apps" / "api" / "migrations"

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def discover() -> list[Path]:
    if not MIGRATIONS_DIR.is_dir():
        sys.exit(f"No migrations directory at {MIGRATIONS_DIR}")
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--status", action="store_true", help="show what would run, apply nothing"
    )
    args = parser.parse_args()

    migrations = discover()
    if not migrations:
        print("No migration files found.")
        return 0

    with psycopg.connect(get_settings().database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_TABLE)
        conn.commit()

        done = applied_versions(conn)
        pending = [m for m in migrations if m.stem not in done]

        if args.status:
            for m in migrations:
                mark = "applied" if m.stem in done else "PENDING"
                print(f"  [{mark:>7}] {m.name}")
            return 0

        if not pending:
            print(f"Up to date — {len(done)} migration(s) already applied.")
            return 0

        for migration in pending:
            print(f"Applying {migration.name} ...", end=" ", flush=True)
            try:
                # Each migration is one transaction: a failure rolls back
                # cleanly and is not recorded as applied.
                with conn.cursor() as cur:
                    cur.execute(migration.read_text())
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration.stem,),
                    )
                conn.commit()
                print("ok")
            except Exception as exc:
                conn.rollback()
                print("FAILED")
                sys.exit(f"\n{migration.name} failed, nothing was recorded:\n{exc}")

        print(f"\nApplied {len(pending)} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
