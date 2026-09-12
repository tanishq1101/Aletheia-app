#!/usr/bin/env python3
"""Copy this database into another one — the local Postgres -> Neon cut-over.

    python scripts/migrate_to_neon.py --to "postgresql://…neon.tech/db?sslmode=require"
    python scripts/migrate_to_neon.py --to "$NEON_URL" --dry-run
    python scripts/migrate_to_neon.py --to "$NEON_URL" --truncate   # re-run

Copies rows only. The target must already have the schema — create it with:

    npx prisma migrate deploy          # applies prisma/migrations/0_init

Why this and not `pg_dump | psql`: Neon's pooled endpoint refuses some of what
pg_dump emits, the local machine may not have a matching client version, and a
row copy that understands the foreign-key order is easier to re-run than a dump
that half-applied. It also means the vector column crosses as text through the
same driver the application uses, instead of through a binary format that has
to agree about pgvector's wire representation on both ends.

Safety:
  * Refuses to run if the target already holds data, unless --truncate.
  * Copies tables in dependency order, inside one transaction. A failure
    anywhere rolls the whole thing back — there is no half-migrated state.
  * Verifies row counts per table afterwards and fails if any disagree.
  * Never writes to the source.
"""

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.core.config import get_settings  # noqa: E402

# Parents before children. Every foreign key points at a table earlier in this
# list, so the copy never has to defer a constraint.
TABLE_ORDER = [
    "users",
    "projects",
    "papers",
    "processing_jobs",
    "paper_pages",
    "paper_sections",
    "paper_chunks",
    "paper_assets",
    "asset_interpretations",
    "conversations",
    "messages",
    "citations",
    "claims",
    "claim_verifications",
    "reproducibility_reports",
    "reproducibility_checks",
    "app_settings",
    "schema_migrations",
]

# Rows per INSERT. Large enough that 459 chunks with 512-float vectors move in
# a couple of statements, small enough not to build a multi-megabyte query.
BATCH = 200


def columns_of(conn, table: str) -> list[str]:
    return [name for name, _ in typed_columns_of(conn, table)]


def typed_columns_of(conn, table: str) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, udt_name FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = %s
             ORDER BY ordinal_position
            """,
            (table,),
        )
        return [(r["column_name"], r["udt_name"]) for r in cur.fetchall()]


def count_of(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) AS n FROM "{table}"')
        return cur.fetchone()["n"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--to", required=True, metavar="URL", help="target connection string"
    )
    parser.add_argument(
        "--from",
        dest="source",
        metavar="URL",
        help="source connection string (default: DATABASE_URL from backend/.env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied and verify the target schema, then stop",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="empty the target's tables first (makes the copy re-runnable)",
    )
    args = parser.parse_args()

    source_url = args.source or get_settings().database_url
    target_url = args.to
    if source_url == target_url:
        sys.exit("Source and target are the same database.")

    print(f"source: {source_url.split('@')[-1]}")
    print(f"target: {target_url.split('@')[-1]}\n")

    with (
        psycopg.connect(source_url, row_factory=dict_row) as src,
        psycopg.connect(target_url, row_factory=dict_row) as dst,
    ):
        # The target must already have the schema; this script copies rows and
        # deliberately does not create tables, so a typo in --to fails here
        # rather than silently building a second, empty database.
        missing = [t for t in TABLE_ORDER if not columns_of(dst, t)]
        if missing:
            sys.exit(
                f"Target is missing {len(missing)} table(s): {', '.join(missing)}\n"
                "Create the schema first:  npx prisma migrate deploy"
            )

        plan = [(t, count_of(src, t), count_of(dst, t)) for t in TABLE_ORDER]
        width = max(len(t) for t in TABLE_ORDER)
        total = 0
        for table, src_n, dst_n in plan:
            total += src_n
            note = f"  (target already holds {dst_n})" if dst_n else ""
            print(f"  {table:{width}}  {src_n:>6} row(s){note}")
        print(f"\n  {'total':{width}}  {total:>6} row(s)")

        occupied = [(t, n) for t, _, n in plan if n]
        if occupied and not args.truncate and not args.dry_run:
            sys.exit(
                "\nTarget is not empty: "
                + ", ".join(f"{t} ({n})" for t, n in occupied)
                + "\nRe-run with --truncate to replace its contents, or point "
                "--to at an empty database."
            )

        if args.dry_run:
            print("\n--dry-run: nothing written. Target schema looks correct.")
            return 0

        with dst.transaction():
            if args.truncate:
                with dst.cursor() as cur:
                    # One statement so the FK graph never has to be satisfied
                    # in the middle of the delete.
                    quoted = ", ".join(f'"{t}"' for t in TABLE_ORDER)
                    cur.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")
                print("\nTruncated target tables.")

            print()
            for table in TABLE_ORDER:
                typed = typed_columns_of(src, table)
                cols = [name for name, _ in typed]
                # psycopg decodes jsonb to dict/list on read but will not infer
                # the type back on write — an unwrapped dict is "cannot adapt
                # type 'dict'". Wrapping is per column, not per value, so a
                # JSON string stored in a jsonb column also round-trips.
                json_cols = {name for name, udt in typed if udt in ("json", "jsonb")}
                target_cols = columns_of(dst, table)
                if cols != target_cols:
                    raise SystemExit(
                        f"Column mismatch on {table}:\n"
                        f"  source: {cols}\n  target: {target_cols}\n"
                        "The target schema is a different version. Re-run "
                        "`npx prisma migrate deploy` against it."
                    )

                quoted_cols = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(["%s"] * len(cols))
                insert = (
                    f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})'
                )

                copied = 0
                with src.cursor(name=f"read_{table}") as read:
                    read.itersize = BATCH
                    read.execute(f'SELECT {quoted_cols} FROM "{table}"')
                    with dst.cursor() as write:
                        def adapt(row) -> tuple:
                            return tuple(
                                Jsonb(row[c])
                                if c in json_cols and row[c] is not None
                                else row[c]
                                for c in cols
                            )

                        batch: list[tuple] = []
                        for row in read:
                            batch.append(adapt(row))
                            if len(batch) >= BATCH:
                                write.executemany(insert, batch)
                                copied += len(batch)
                                batch.clear()
                        if batch:
                            write.executemany(insert, batch)
                            copied += len(batch)
                print(f"  {table:{width}}  copied {copied:>6}")

        # Outside the transaction: compare what actually landed.
        print("\nVerifying…")
        mismatched = []
        for table in TABLE_ORDER:
            src_n, dst_n = count_of(src, table), count_of(dst, table)
            if src_n != dst_n:
                mismatched.append(f"{table}: source {src_n}, target {dst_n}")
        if mismatched:
            print("Row counts DISAGREE:", file=sys.stderr)
            for m in mismatched:
                print(f"  ✗ {m}", file=sys.stderr)
            return 1

        print(f"All {len(TABLE_ORDER)} tables match ({total} rows).")

    print(
        "\nNext:\n"
        "  1. point DATABASE_URL in backend/.env at the target\n"
        "  2. python scripts/verify_schema.py       # raw indexes + CHECKs\n"
        "  3. python scripts/backfill_chroma.py     # re-index vectors\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
