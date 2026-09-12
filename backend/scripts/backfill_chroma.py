#!/usr/bin/env python3
"""Sync chunk embeddings from Postgres into Chroma.

Postgres is the source of truth; this makes Chroma agree with it. Run it after
provisioning a Chroma instance, after any ingestion that logged a mirror
failure, and after switching databases.

    python scripts/backfill_chroma.py              # sync what is missing
    python scripts/backfill_chroma.py --rebuild    # drop the collection first
    python scripts/backfill_chroma.py --status     # compare counts, write nothing

Idempotent: chunk ids are the Chroma ids, so re-running upserts the same rows
rather than duplicating them.
"""

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402
from app.services.vector_store import (  # noqa: E402
    VectorStoreError,
    delete_collection,
    get_collection,
    upsert_chunks,
)

# Vectors are 512 floats each; a few thousand per request keeps the HTTP body
# reasonable without making a round trip per chunk.
BATCH = 500

ROWS_SQL = """
    SELECT c.id           AS chunk_id,
           c.paper_id,
           p.project_id,
           c.content,
           c.chunk_index,
           c.section,
           pg.page_number,
           c.embedding
      FROM paper_chunks c
      JOIN papers p       ON p.id = c.paper_id
 LEFT JOIN paper_pages pg ON pg.id = c.page_id
     WHERE c.embedding IS NOT NULL
  ORDER BY c.paper_id, c.chunk_index
"""


def parse_vector(raw) -> list[float]:
    """pgvector comes back as its text form unless the type is registered."""
    if isinstance(raw, list):
        return [float(x) for x in raw]
    return [float(x) for x in str(raw).strip("[]").split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="delete the collection before syncing (use after changing the "
        "embedding model, where old vectors are in a different space)",
    )
    parser.add_argument(
        "--status", action="store_true", help="report counts, write nothing"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.chroma_enabled:
        sys.exit("CHROMA_ENABLED is false — nothing to sync.")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM paper_chunks WHERE embedding IS NOT NULL"
            )
            pg_count = cur.fetchone()["n"]

        try:
            collection = get_collection()
        except VectorStoreError as exc:
            sys.exit(
                f"Chroma is unreachable at {settings.chroma_host}:"
                f"{settings.chroma_port} — {exc}\n"
                "Start it with: docker compose up -d chroma"
            )

        print(f"Postgres: {pg_count} embedded chunk(s)")
        print(f"Chroma  : {collection.count()} vector(s) in "
              f"'{settings.chroma_collection}'")

        if args.status:
            return 0

        if args.rebuild:
            print(f"Deleting collection '{settings.chroma_collection}'…")
            delete_collection()
            collection = get_collection()

        with conn.cursor(name="backfill") as cur:
            cur.itersize = BATCH
            cur.execute(ROWS_SQL)

            written = 0
            batch: list[dict] = []

            def flush() -> int:
                if not batch:
                    return 0
                # One upsert per paper: project_id and paper_id are per-call
                # arguments, and a batch can straddle two papers.
                by_paper: dict[tuple, list[dict]] = {}
                for row in batch:
                    by_paper.setdefault(
                        (row["project_id"], row["paper_id"]), []
                    ).append(row)

                total = 0
                for (project_id, paper_id), rows in by_paper.items():
                    total += upsert_chunks(
                        project_id=project_id,
                        paper_id=paper_id,
                        chunk_ids=[r["chunk_id"] for r in rows],
                        vectors=[parse_vector(r["embedding"]) for r in rows],
                        contents=[r["content"] for r in rows],
                        metadatas=[
                            {
                                "chunk_index": r["chunk_index"],
                                "section": r["section"] or "",
                                "page_number": r["page_number"],
                            }
                            for r in rows
                        ],
                    )
                batch.clear()
                return total

            for row in cur:
                batch.append(row)
                if len(batch) >= BATCH:
                    written += flush()
                    print(f"  … {written}/{pg_count}")
            written += flush()

    print(f"Synced {written} vector(s). Chroma now holds {get_collection().count()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
