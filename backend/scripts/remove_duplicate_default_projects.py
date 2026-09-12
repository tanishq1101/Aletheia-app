#!/usr/bin/env python3
"""Remove the empty duplicate default projects left by an old race.

`POST /projects/default` used to be "list, and create if empty" — two round
trips with a gap. A React development double-mount fell into that gap and
created two "My Library" projects 171 ms apart; the UI then selected the newer,
empty one and the uploaded paper appeared to have vanished. The endpoint now
decides this under a per-user advisory lock, so the race cannot recur, but the
rows it already produced are still there.

This removes them, and is deliberately conservative about what "them" means. A
project is only a candidate when **all** of these hold:

  * it is not the oldest project for its user — the oldest is the default, and
    is never touched;
  * it holds no papers, so there is nothing to lose;
  * it has no description, and its name is exactly the default one. Two
    projects a user deliberately named the same thing is a legitimate thing to
    want, and this must not delete one of those.

The emptiness check is repeated inside the deleting transaction, so a paper
uploaded between the survey and the delete keeps its project.

    python backend/scripts/remove_duplicate_default_projects.py           # survey
    python backend/scripts/remove_duplicate_default_projects.py --apply   # delete

Exit code 0 when there is nothing to do or the deletion succeeded, 1 on a
refusal. Prints exactly what it would remove before removing anything.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.core.config import get_settings  # noqa: E402

# Must match app/api/projects.py. Imported rather than retyped so the two
# cannot drift into disagreeing about which name is the default one.
from app.api.projects import DEFAULT_PROJECT_NAME  # noqa: E402


CANDIDATES = """
SELECT
    p.id,
    p.name,
    p.user_id,
    p.created_at,
    (SELECT COUNT(*) FROM papers WHERE project_id = p.id) AS papers
FROM projects p
WHERE p.name = %(default_name)s
  AND p.description IS NULL
  -- Never the user's oldest project: that one is the default itself.
  AND p.created_at > (
      SELECT MIN(created_at) FROM projects WHERE user_id = p.user_id
  )
  AND NOT EXISTS (SELECT 1 FROM papers WHERE project_id = p.id)
ORDER BY p.user_id, p.created_at
"""


def survey(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CANDIDATES, {"default_name": DEFAULT_PROJECT_NAME})
        return cur.fetchall()


def report(rows: list[dict]) -> None:
    if not rows:
        print("No empty duplicate default projects found. Nothing to do.")
        return
    print(f"{len(rows)} empty duplicate '{DEFAULT_PROJECT_NAME}' project(s):\n")
    for row in rows:
        print(
            f"  {row['id']}  user={row['user_id']}  "
            f"created={row['created_at']:%Y-%m-%d %H:%M:%S}  papers={row['papers']}"
        )
    print()


def delete(conn: psycopg.Connection, rows: list[dict]) -> int:
    removed = 0
    with conn.cursor(row_factory=dict_row) as cur:
        for row in rows:
            # Re-checked here, inside the transaction that deletes: the survey
            # above is not a lock, and a paper uploaded in between would
            # otherwise be destroyed by a cascade.
            cur.execute(
                """
                DELETE FROM projects
                WHERE id = %(id)s
                  AND name = %(default_name)s
                  AND description IS NULL
                  AND NOT EXISTS (SELECT 1 FROM papers WHERE project_id = %(id)s)
                  AND created_at > (
                      SELECT MIN(created_at) FROM projects WHERE user_id = %(user_id)s
                  )
                RETURNING id
                """,
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "default_name": DEFAULT_PROJECT_NAME,
                },
            )
            if cur.fetchone() is None:
                print(f"  skipped {row['id']} — no longer matches; it changed under us")
            else:
                removed += 1
                print(f"  removed {row['id']}")
    return removed


def main(apply: bool = False) -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    with psycopg.connect(settings.database_url) as conn:
        rows = survey(conn)
        report(rows)
        if not rows:
            return 0
        if not apply:
            print("Dry run. Rerun with --apply to remove them.")
            return 0
        removed = delete(conn, rows)
        conn.commit()
        print(f"\nRemoved {removed} of {len(rows)} project(s).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this the script only reports.",
    )
    raise SystemExit(main(**vars(parser.parse_args())))
