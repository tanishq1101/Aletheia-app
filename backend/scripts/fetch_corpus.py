#!/usr/bin/env python3
"""Fetch the Sprint 6 benchmark corpus from arXiv.

The PDFs are ~30MB of binaries that are not ours to redistribute, so they are
gitignored. This script plus the checked-in manifest reproduces them exactly:
every paper is pinned by SHA-256, so a corpus that has silently changed under a
benchmark is a hard failure rather than a quietly different number.

Trust-on-first-use: a manifest entry with `sha256: null` records the hash it
downloaded. Once recorded, every later run *verifies* against it. That way the
pin is real rather than copied from somewhere unverifiable.

    python scripts/fetch_corpus.py            # download what is missing, verify the rest
    python scripts/fetch_corpus.py --verify   # verify only, download nothing
    python scripts/fetch_corpus.py --force    # re-download everything
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "datasets" / "corpus" / "manifest.json"
PDF_DIR = REPO_ROOT / "datasets" / "corpus" / "pdfs"

# arXiv asks automated clients to identify themselves and not hammer the site.
USER_AGENT = "ai-research-intelligence-platform/0.1 (Sprint 6 benchmark corpus)"
REQUEST_DELAY_SECONDS = 3.0
TIMEOUT_SECONDS = 120.0


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def pdf_path(key: str) -> Path:
    return PDF_DIR / f"{key}.pdf"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


def download(client: httpx.Client, arxiv_id: str, destination: Path) -> None:
    """Download one PDF, failing loudly on anything that is not a PDF.

    arXiv serves an HTML page for a withdrawn or mistyped ID with a 200 status,
    so checking the status code alone would happily write an HTML file with a
    .pdf name and only fail much later inside the parser.
    """
    response = client.get(pdf_url(arxiv_id), follow_redirects=True)
    response.raise_for_status()

    body = response.content
    if not body.startswith(b"%PDF"):
        content_type = response.headers.get("content-type", "unknown")
        raise RuntimeError(
            f"arXiv returned {content_type} rather than a PDF for {arxiv_id} "
            f"({len(body)} bytes). Check the ID."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="verify existing files, download nothing"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download even if the file exists"
    )
    args = parser.parse_args()

    manifest = load_manifest()
    papers = manifest["papers"]
    failures: list[str] = []
    recorded = 0

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS) as client:
        for index, paper in enumerate(papers):
            key = paper["key"]
            arxiv_id = paper["arxiv_id"]
            destination = pdf_path(key)
            needs_download = args.force or not destination.exists()

            if needs_download and args.verify:
                failures.append(f"{key}: missing ({destination.name})")
                print(f"  MISSING  {key:10s} {arxiv_id}")
                continue

            if needs_download:
                # Be a polite client: space out requests, but do not sleep
                # before the first one or after the last.
                if index > 0:
                    time.sleep(REQUEST_DELAY_SECONDS)
                print(f"  fetching {key:10s} {arxiv_id} ...", end="", flush=True)
                try:
                    download(client, arxiv_id, destination)
                except Exception as exc:
                    print(" FAILED")
                    failures.append(f"{key}: {exc}")
                    continue
                print(f" {destination.stat().st_size / 1_000_000:.1f} MB")

            actual = sha256_of(destination)
            expected = paper.get("sha256")

            if expected is None:
                paper["sha256"] = actual
                recorded += 1
                print(f"  RECORDED {key:10s} sha256={actual[:16]}...")
            elif actual != expected:
                failures.append(
                    f"{key}: SHA-256 mismatch — expected {expected[:16]}..., "
                    f"got {actual[:16]}... The corpus has changed under the benchmark."
                )
                print(f"  MISMATCH {key:10s}")
            else:
                print(f"  ok       {key:10s} {destination.stat().st_size / 1_000_000:.1f} MB")

    if recorded:
        save_manifest(manifest)
        print(f"\nRecorded {recorded} new SHA-256 pin(s) into {MANIFEST.name}.")

    if failures:
        print(f"\n{len(failures)} problem(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"\nAll {len(papers)} paper(s) present and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
