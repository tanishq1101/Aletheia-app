#!/usr/bin/env python3
"""Ingest the benchmark corpus into a project, through the real pipeline.

Deliberately drives the actual `POST /projects/{id}/papers` endpoint in-process
rather than reimplementing upload. Validation, SHA-256 duplicate detection,
storage, the paper/job records, and the parse → chunk → embed stages are all
the same code paths a browser upload takes. A script that inlined its own
version of that would drift from the endpoint and quietly benchmark a pipeline
nobody actually uses.

In-process via TestClient (not HTTP against a running server) for two reasons:
no server needs to be up, and background tasks run synchronously — so when this
returns, ingestion has genuinely finished rather than being merely queued.

    python scripts/ingest_corpus.py            # ingest what is missing
    python scripts/ingest_corpus.py --status   # report only, ingest nothing
    python scripts/ingest_corpus.py --reset    # delete the project and start over

Writes the real per-paper page count back into the corpus manifest so benchmark
gold-page labels can be range-checked against the corpus rather than trusted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

MANIFEST = REPO_ROOT / "datasets" / "corpus" / "manifest.json"
PDF_DIR = REPO_ROOT / "datasets" / "corpus" / "pdfs"

# The corpus lives in its own project so a benchmark run cannot be polluted by
# whatever else happens to be in the dev database.
PROJECT_NAME = "Sprint 6 Benchmark Corpus"


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


def _connection():
    from app.db.session import get_connection

    return get_connection()


def find_project(client) -> dict | None:
    response = client.get("/projects")
    response.raise_for_status()
    for project in response.json():
        if project["name"] == PROJECT_NAME:
            return project
    return None


def ensure_project(client) -> dict:
    existing = find_project(client)
    if existing is not None:
        return existing
    response = client.post(
        "/projects",
        json={
            "name": PROJECT_NAME,
            "description": (
                "Ten arXiv papers pinned in datasets/corpus/manifest.json. "
                "Backing corpus for the Sprint 6 evaluation benchmark."
            ),
        },
    )
    response.raise_for_status()
    print(f"Created project {PROJECT_NAME!r}")
    return response.json()


def delete_project(project_id: str) -> None:
    """Papers, pages, sections, chunks, and jobs all cascade from the project."""
    with _connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def paper_stats(project_id: str) -> dict[str, dict]:
    """Per-filename ingestion state, straight from the database."""
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.filename,
                   p.id::text                AS paper_id,
                   p.title,
                   p.status,
                   p.page_count,
                   (SELECT count(*) FROM paper_pages   pp WHERE pp.paper_id = p.id) AS pages,
                   (SELECT count(*) FROM paper_sections ps WHERE ps.paper_id = p.id) AS sections,
                   (SELECT count(*) FROM paper_chunks  pc WHERE pc.paper_id = p.id) AS chunks,
                   (SELECT count(*) FROM paper_chunks  pc
                     WHERE pc.paper_id = p.id AND pc.embedding IS NOT NULL)          AS embedded,
                   (SELECT j.error FROM processing_jobs j
                     WHERE j.paper_id = p.id ORDER BY j.created_at DESC LIMIT 1)     AS error
              FROM papers p
             WHERE p.project_id = %s
            """,
            (project_id,),
        )
        return {row["filename"]: dict(row) for row in cur.fetchall()}


def upload(client, project_id: str, key: str, path: Path) -> str:
    """Upload one PDF. Returns a short status word for the report line."""
    with path.open("rb") as handle:
        response = client.post(
            f"/projects/{project_id}/papers",
            files={"file": (f"{key}.pdf", handle, "application/pdf")},
        )
    if response.status_code == 409:
        return "duplicate"
    if response.status_code != 201:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    return "ingested"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="report only")
    parser.add_argument(
        "--reset", action="store_true", help="delete the project and re-ingest"
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    papers = manifest["papers"]

    missing = [p["key"] for p in papers if not (PDF_DIR / f"{p['key']}.pdf").exists()]
    if missing and not args.status:
        print(
            f"Corpus incomplete — missing {', '.join(missing)}.\n"
            "Run: python scripts/fetch_corpus.py",
            file=sys.stderr,
        )
        return 1

    with _client() as client:
        if args.reset:
            existing = find_project(client)
            if existing is not None:
                delete_project(existing["id"])
                print(f"Deleted project {existing['id']} and all its papers.")

        project = ensure_project(client)
        project_id = project["id"]
        print(f"Project {project_id}\n")

        if not args.status:
            already = paper_stats(project_id)
            for paper in papers:
                key = paper["key"]
                filename = f"{key}.pdf"
                if filename in already and already[filename]["status"] == "ready":
                    print(f"  skip     {key:10s} already ingested")
                    continue
                print(f"  ingest   {key:10s} ...", end="", flush=True)
                try:
                    outcome = upload(client, project_id, key, PDF_DIR / filename)
                except Exception as exc:
                    print(f" FAILED: {exc}")
                    continue
                print(f" {outcome}")
            print()

        stats = paper_stats(project_id)

    # --- report + write real page counts back into the manifest ---
    failures: list[str] = []
    updated = 0
    header = f"  {'key':<10} {'status':<10} {'pages':>5} {'sect':>5} {'chunks':>7} {'embed':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for paper in papers:
        key = paper["key"]
        row = stats.get(f"{key}.pdf")
        if row is None:
            failures.append(f"{key}: never ingested")
            print(f"  {key:<10} {'MISSING':<10}")
            continue

        print(
            f"  {key:<10} {row['status']:<10} {row['pages']:>5} "
            f"{row['sections']:>5} {row['chunks']:>7} {row['embedded']:>6}"
        )

        if row["status"] != "ready":
            failures.append(f"{key}: status={row['status']} error={row['error']}")
        elif row["chunks"] == 0:
            failures.append(f"{key}: ready but produced no chunks")
        elif row["embedded"] != row["chunks"]:
            # A half-embedded paper retrieves partially and looks fine.
            failures.append(
                f"{key}: {row['embedded']}/{row['chunks']} chunks embedded"
            )

        if row["pages"] and paper.get("page_count") != row["pages"]:
            paper["page_count"] = row["pages"]
            updated += 1

    if updated:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"\nRecorded page counts for {updated} paper(s) into {MANIFEST.name}.")

    totals = [stats.get(f"{p['key']}.pdf") for p in papers]
    present = [row for row in totals if row]
    print(
        f"\n{len(present)}/{len(papers)} papers · "
        f"{sum(r['pages'] for r in present)} pages · "
        f"{sum(r['chunks'] for r in present)} chunks · "
        f"{sum(r['embedded'] for r in present)} embedded"
    )

    if failures:
        print(f"\n{len(failures)} problem(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
