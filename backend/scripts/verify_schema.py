#!/usr/bin/env python3
"""Assert the database objects Prisma cannot express are still present.

Run after every migration — `npm run db:verify` from the repo root.

The failure this exists to catch is silent. `prisma migrate dev` generates its
SQL by diffing the schema file against the database, and because Prisma's
schema language has no syntax for an HNSW index, a partial index, an expression
index or a CHECK constraint, it reads all of them as drift and proposes DROP
statements. Applying such a migration does not break anything visibly:

  * dropping idx_paper_chunks_embedding leaves vector search *working*, just
    sequentially scanning every chunk — you find out months later, as latency;
  * dropping the CHECK constraints leaves inserts *working*, just no longer
    rejecting status='banana'.

Both are the kind of regression that a test suite against a fresh database
would never see, because the schema it builds is the broken one.

Exit code 0 when everything is present, 1 when anything is missing.
"""

import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.core.config import get_settings  # noqa: E402

# name -> a fragment that must appear in the catalog's definition, so that an
# index which exists but was rebuilt as the wrong kind still fails.
REQUIRED_INDEXES = {
    "idx_paper_chunks_embedding": "USING hnsw",
    "idx_papers_project_sha256": "WHERE (sha256 IS NOT NULL)",
    "claim_verifications_unique_scope_idx": "COALESCE",
}

# Every table that carries at least one CHECK, and how many it should have.
EXPECTED_CHECKS = {
    "app_settings": 4,
    "claims": 1,
    "claim_verifications": 1,
    "messages": 1,
    "paper_assets": 2,
    "paper_pages": 1,
    "paper_sections": 2,
    "papers": 1,
    "processing_jobs": 3,
    "projects": 1,
    "reproducibility_checks": 1,
}


def main() -> int:
    settings = get_settings()
    failures: list[str] = []

    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
        )
        found = dict(cur.fetchall())

        for name, fragment in REQUIRED_INDEXES.items():
            definition = found.get(name)
            if definition is None:
                failures.append(
                    f"index {name} is MISSING — re-apply it from "
                    f"prisma/migrations/0_init/migration.sql"
                )
            elif fragment not in definition:
                failures.append(
                    f"index {name} exists but was rebuilt incorrectly: "
                    f"expected {fragment!r} in its definition, got:\n    {definition}"
                )

        cur.execute(
            """
            SELECT rel.relname, count(*)
              FROM pg_constraint con
              JOIN pg_class rel ON rel.oid = con.conrelid
             WHERE con.connamespace = 'public'::regnamespace AND con.contype = 'c'
             GROUP BY rel.relname
            """
        )
        counts = dict(cur.fetchall())

    for table, expected in EXPECTED_CHECKS.items():
        actual = counts.get(table, 0)
        if actual < expected:
            failures.append(
                f"table {table} has {actual} CHECK constraint(s), expected "
                f"{expected} — a migration dropped {expected - actual} of them"
            )

    host = settings.database_url.split("@")[-1]
    if failures:
        print(f"Schema verification FAILED against {host}\n", file=sys.stderr)
        for failure in failures:
            print(f"  ✗ {failure}", file=sys.stderr)
        print(
            "\nThese objects have no Prisma schema syntax, so `prisma migrate`\n"
            "proposes dropping them. Read generated migration SQL before\n"
            "applying it — see the header of prisma/schema.prisma.",
            file=sys.stderr,
        )
        return 1

    total_checks = sum(counts.get(t, 0) for t in EXPECTED_CHECKS)
    print(
        f"Schema OK on {host}: "
        f"{len(REQUIRED_INDEXES)} raw index(es), {total_checks} CHECK constraint(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
