#!/usr/bin/env python3
"""Copy uploaded files from a local storage directory into Cloudflare R2.

Switching STORAGE_BACKEND from `local` to `r2` moves where the API *looks* for
a paper's bytes; it does not move the bytes. Every `papers.storage_path` and
`paper_assets.storage_path` already in Postgres keeps pointing at a key that R2
does not have yet, so the library lists papers whose reader, figures and tables
all fail. This copies them across under their existing keys, which is why no
database row needs to change.

    python scripts/backfill_r2.py --status     # what is where, write nothing
    python scripts/backfill_r2.py --dry-run    # name every file that would move
    python scripts/backfill_r2.py              # copy what is missing
    python scripts/backfill_r2.py --verify     # re-read from R2, check digests
    python scripts/backfill_r2.py --force      # re-upload even if R2 has the key

Idempotent: the key is the object name, so re-running overwrites identical
bytes rather than duplicating them. Safe to interrupt and re-run.

`papers.sha256` is the digest recorded at upload. A local file that does not
match it is *not* uploaded — a wrong file under the right key is worse than a
missing one, because nothing downstream would ever notice.

Exits non-zero if any file could not be accounted for, so this cannot look like
it succeeded when part of the library is unrecoverable.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402
from app.services.storage import (  # noqa: E402
    LocalStorage,
    R2Storage,
    StorageError,
)

# `storage_path` is NOT NULL on papers and nullable on paper_assets, so the
# asset query filters. Ordered so output groups by paper rather than by table.
PAPERS_SQL = """
    SELECT p.id::text     AS row_id,
           p.storage_path AS key,
           p.filename     AS label,
           p.sha256       AS sha256
      FROM papers p
     ORDER BY p.created_at
"""

ASSETS_SQL = """
    SELECT a.id::text     AS row_id,
           a.storage_path AS key,
           a.kind || ' #' || a.asset_index AS label,
           NULL           AS sha256
      FROM paper_assets a
     WHERE a.storage_path IS NOT NULL
     ORDER BY a.paper_id, a.asset_index
"""


class Tally:
    """What happened to every row, so the summary is counted, not estimated."""

    def __init__(self) -> None:
        self.copied: list[str] = []
        self.already: list[str] = []
        self.missing: list[str] = []
        self.mismatched: list[str] = []
        self.failed: list[str] = []

    @property
    def unrecoverable(self) -> list[str]:
        return self.missing + self.mismatched + self.failed


def build_backends(args) -> tuple[LocalStorage, R2Storage]:
    """Both backends explicitly, not via build_storage().

    build_storage() returns whichever one STORAGE_BACKEND names, and this
    script needs both at once — that switch has usually already been flipped
    to `r2` by the time anyone runs this.
    """
    settings = get_settings()
    source_root = Path(args.source_dir) if args.source_dir else settings.storage_root
    if not source_root.is_dir():
        sys.exit(
            f"Source directory does not exist: {source_root}\n"
            "Point --source-dir at the storage directory the files were "
            "written to (LOCAL_STORAGE_DIR on the old deployment)."
        )
    try:
        r2 = R2Storage(
            endpoint=settings.r2_endpoint,
            bucket=settings.r2_bucket,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            region=settings.r2_region,
        )
    except StorageError as exc:
        sys.exit(f"{exc}\nSee backend/.env.example for every R2_* variable.")
    return LocalStorage(source_root), r2


def transfer(row, local, r2, args, tally: Tally) -> None:
    key, label = row["key"], row["label"]
    where = f"{label} ({key})"

    if not args.force:
        try:
            if r2.exists(key=key):
                tally.already.append(where)
                return
        except StorageError as exc:
            tally.failed.append(f"{where} — could not check R2: {exc}")
            return

    if not local.exists(key=key):
        tally.missing.append(where)
        return

    try:
        data = local.read(key=key)
    except StorageError as exc:
        tally.failed.append(f"{where} — unreadable locally: {exc}")
        return

    # The digest recorded at upload. A local file that disagrees with it is a
    # different file; uploading it would put wrong bytes under a right key.
    if row["sha256"]:
        actual = hashlib.sha256(data).hexdigest()
        if actual != row["sha256"]:
            tally.mismatched.append(
                f"{where} — local file is sha256 {actual[:12]}…, "
                f"database recorded {row['sha256'][:12]}…"
            )
            return

    if args.dry_run:
        tally.copied.append(f"{where} — {len(data):,} bytes (dry run)")
        return

    try:
        r2.store(key=key, data=data)
    except StorageError as exc:
        tally.failed.append(f"{where} — upload failed: {exc}")
        return

    if args.verify:
        try:
            returned = r2.read(key=key)
        except StorageError as exc:
            tally.failed.append(f"{where} — stored but unreadable: {exc}")
            return
        if hashlib.sha256(returned).hexdigest() != hashlib.sha256(data).hexdigest():
            tally.failed.append(f"{where} — bytes differ after round trip")
            return

    tally.copied.append(f"{where} — {len(data):,} bytes")


def report(tally: Tally, verified: bool) -> int:
    print()
    rows = [
        ("copied" + (" (verified)" if verified else ""), len(tally.copied)),
        ("already in R2", len(tally.already)),
        ("missing locally", len(tally.missing)),
        ("digest mismatch", len(tally.mismatched)),
        ("failed", len(tally.failed)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, count in rows:
        print(f"  {label:<{width}}  {count:>4}")

    if tally.missing:
        print(
            "\nNot on this machine. These rows point at bytes that are not in "
            "the source directory — from the paused deployment's disk, most "
            "likely. They must be re-uploaded through the app:"
        )
        for item in tally.missing:
            print(f"  - {item}")
    for title, items in (
        ("Digest mismatch — NOT uploaded", tally.mismatched),
        ("Failed", tally.failed),
    ):
        if items:
            print(f"\n{title}:")
            for item in items:
                print(f"  - {item}")

    if tally.unrecoverable:
        print(
            f"\n{len(tally.unrecoverable)} file(s) unaccounted for. "
            "The rest of the library is now served from R2."
        )
        return 1
    print("\nEvery recorded file is in R2.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy local paper and asset files into R2 under their existing keys."
    )
    parser.add_argument("--status", action="store_true",
                        help="report what is where, write nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="name every file that would be copied, write nothing")
    parser.add_argument("--verify", action="store_true",
                        help="read each object back from R2 and compare bytes")
    parser.add_argument("--force", action="store_true",
                        help="upload even when R2 already holds the key")
    parser.add_argument("--source-dir",
                        help="the local storage directory to copy from "
                             "(default: LOCAL_STORAGE_DIR)")
    args = parser.parse_args()

    settings = get_settings()
    local, r2 = build_backends(args)

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(PAPERS_SQL)
            papers = cur.fetchall()
            cur.execute(ASSETS_SQL)
            assets = cur.fetchall()

    rows = papers + assets
    print(f"Source : {local._root}")
    print(f"Target : {settings.r2_bucket} at {settings.r2_endpoint}")
    print(f"Rows   : {len(papers)} paper(s), {len(assets)} asset(s)")

    if args.status:
        # A HEAD per key. Counts only — nothing is read or written.
        present = missing_local = 0
        for row in rows:
            try:
                if r2.exists(key=row["key"]):
                    present += 1
                    continue
            except StorageError as exc:
                sys.exit(f"Could not reach R2: {exc}")
            if not local.exists(key=row["key"]):
                missing_local += 1
        print(f"\n  in R2                {present:>5}")
        print(f"  not in R2            {len(rows) - present:>5}")
        print(f"  of those, also absent locally {missing_local:>5}")
        return 0

    tally = Tally()
    for row in rows:
        transfer(row, local, r2, args, tally)

    if args.dry_run:
        for item in tally.copied:
            print(f"  would copy {item}")
    return report(tally, verified=args.verify and not args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
