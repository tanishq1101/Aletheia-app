#!/usr/bin/env python3
"""Hand the seeded development user's library to a real Clerk account.

Before Clerk, every row belonged to one seeded UUID (`DEV_USER_ID`, migration
0002). Turning authentication on does not move that data: `_resolve_user` in
app/core/auth.py provisions a *new* `users` row from the Clerk subject on first
sign-in, and the ownership guard then correctly hides everything the seeded
user owns. The library looks empty, and nothing is wrong except that nobody
told the database the two are the same person.

This transfers ownership of the seeded user's projects. It moves only
`projects.user_id`: papers, chunks, conversations, claims and assets are all
reached through `project_id`, so re-parenting the project carries the whole
tree with it and there is no second place for the two to disagree.

Sign in through the UI once before running this, so the Clerk user row exists.

    python backend/scripts/adopt_dev_user_library.py                     # survey
    python backend/scripts/adopt_dev_user_library.py --apply             # move
    python backend/scripts/adopt_dev_user_library.py --email me@x.com --apply

With one real account in the database the target is unambiguous and need not be
named. With several, --email or --clerk-id is required rather than guessed:
picking the wrong one hands someone else's account a library.

Exit code 0 when there is nothing to do or the move succeeded, 1 on a refusal.
Re-running after a successful move is a no-op, not a second transfer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.core.config import DEV_USER_ID, get_settings  # noqa: E402


# Real accounts only. The seeded user has no Clerk subject by definition
# (migration 0011 documents the NULL), so this cannot return the source.
REAL_USERS = """
SELECT id, clerk_user_id, email, username
FROM users
WHERE clerk_user_id IS NOT NULL
ORDER BY created_at
"""

OWNED_PROJECTS = """
SELECT
    p.id,
    p.name,
    p.created_at,
    (SELECT COUNT(*) FROM papers WHERE project_id = p.id) AS papers
FROM projects p
WHERE p.user_id = %s
ORDER BY p.created_at
"""


def resolve_target(conn, *, email: str | None, clerk_id: str | None) -> dict:
    """The account to hand the library to, or exit with a reason."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REAL_USERS)
        users = cur.fetchall()

    if not users:
        sys.exit(
            "No Clerk-backed account exists yet. Sign in through the UI once so "
            "the user row is provisioned, then re-run. (If sign-in itself is "
            "failing, that is the thing to fix first — not this.)"
        )

    if clerk_id:
        matches = [u for u in users if u["clerk_user_id"] == clerk_id]
        if not matches:
            sys.exit(f"No account with clerk_user_id {clerk_id!r}.")
        return matches[0]

    if email:
        matches = [u for u in users if (u["email"] or "").lower() == email.lower()]
        if not matches:
            known = ", ".join(sorted(u["email"] or "<no email>" for u in users))
            sys.exit(f"No account with email {email!r}. Known: {known}")
        if len(matches) > 1:
            sys.exit(f"{len(matches)} accounts share {email!r}; use --clerk-id.")
        return matches[0]

    if len(users) > 1:
        listing = "\n".join(
            f"    {u['email'] or '<no email>'}  clerk_user_id={u['clerk_user_id']}"
            for u in users
        )
        sys.exit(
            f"{len(users)} real accounts exist, so the target is ambiguous.\n"
            f"Re-run with --email or --clerk-id:\n{listing}"
        )

    return users[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Target account's email.")
    parser.add_argument("--clerk-id", help="Target account's Clerk subject.")
    parser.add_argument(
        "--apply", action="store_true", help="Perform the move (default: survey)."
    )
    args = parser.parse_args()

    with psycopg.connect(get_settings().database_url) as conn:
        target = resolve_target(conn, email=args.email, clerk_id=args.clerk_id)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(OWNED_PROJECTS, (DEV_USER_ID,))
            projects = cur.fetchall()

        label = target["email"] or target["username"] or target["clerk_user_id"]
        if not projects:
            print(
                f"The development user owns no projects. Nothing to move "
                f"(already adopted by {label}?)."
            )
            return

        papers = sum(p["papers"] for p in projects)
        print(f"Development user {DEV_USER_ID} owns:")
        for p in projects:
            print(f"    {p['name']!r}  ({p['papers']} papers)  {p['created_at']:%Y-%m-%d}")
        print(f"  {len(projects)} projects, {papers} papers")
        print(f"\nTarget account: {label}  (id={target['id']})")

        if not args.apply:
            print("\nSurvey only. Re-run with --apply to move them.")
            return

        # One statement, one transaction, and re-checking the owner inside it:
        # a project created by someone else between the survey and here must
        # not be swept up, and a second run must not move anything twice.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE projects SET user_id = %s WHERE user_id = %s",
                (target["id"], DEV_USER_ID),
            )
            moved = cur.rowcount
        conn.commit()

        print(f"\nMoved {moved} projects to {label}.")
        if moved != len(projects):
            print(
                f"  Note: surveyed {len(projects)} but moved {moved} — the set "
                "changed between the survey and the update. Re-run the survey."
            )
        print("The seeded development user is left in place; only ownership moved.")


if __name__ == "__main__":
    main()
