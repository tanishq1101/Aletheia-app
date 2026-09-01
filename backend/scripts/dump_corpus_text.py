#!/usr/bin/env python3
"""Dump the corpus text *as this pipeline extracted it*.

Benchmark questions have to be written against what the system actually sees,
not against the PDF as rendered or against recollection of the paper. If
extraction dropped a table or mangled a formula, a question written from the
original would be unanswerable for reasons that have nothing to do with
retrieval quality — and the benchmark would be measuring the wrong thing.

    python scripts/dump_corpus_text.py bert            # one paper, all pages
    python scripts/dump_corpus_text.py bert --pages 3-5
    python scripts/dump_corpus_text.py --sections      # section outline, all papers
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

PROJECT_NAME = "Sprint 6 Benchmark Corpus"


def _connection():
    from app.db.session import get_connection

    return get_connection()


def parse_pages(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    if "-" in spec:
        low, high = spec.split("-", 1)
        return int(low), int(high)
    return int(spec), int(spec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key", nargs="?", help="manifest key, e.g. bert")
    parser.add_argument("--pages", help="page or range, e.g. 3 or 3-5")
    parser.add_argument("--sections", action="store_true", help="section outline only")
    parser.add_argument("--chars", type=int, default=0, help="truncate each page")
    args = parser.parse_args()

    page_range = parse_pages(args.pages)

    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (PROJECT_NAME,))
        project = cur.fetchone()
        if project is None:
            print(
                f"No project {PROJECT_NAME!r}. Run scripts/ingest_corpus.py.",
                file=sys.stderr,
            )
            return 1
        project_id = project["id"]

        if args.sections:
            cur.execute(
                """
                SELECT p.filename, s.section_index, s.level, s.title, s.start_page
                  FROM paper_sections s
                  JOIN papers p ON p.id = s.paper_id
                 WHERE p.project_id = %s
              ORDER BY p.filename, s.section_index
                """,
                (project_id,),
            )
            current = None
            for row in cur.fetchall():
                if row["filename"] != current:
                    current = row["filename"]
                    print(f"\n=== {current} ===")
                indent = "  " * max(0, row["level"] - 1)
                print(f"  p{row['start_page']:>3}  {indent}{row['title']}")
            return 0

        if not args.key:
            parser.error("a paper key is required unless --sections is given")

        cur.execute(
            """
            SELECT pg.page_number, pg.cleaned_text, pg.token_count
              FROM paper_pages pg
              JOIN papers p ON p.id = pg.paper_id
             WHERE p.project_id = %s AND p.filename = %s
          ORDER BY pg.page_number
            """,
            (project_id, f"{args.key}.pdf"),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"No pages for {args.key!r}.", file=sys.stderr)
        return 1

    for row in rows:
        number = row["page_number"]
        if page_range and not (page_range[0] <= number <= page_range[1]):
            continue
        text = row["cleaned_text"] or ""
        if args.chars:
            text = text[: args.chars]
        print(f"\n{'=' * 70}\nPAGE {number}  ({row['token_count']} tokens)\n{'=' * 70}")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
