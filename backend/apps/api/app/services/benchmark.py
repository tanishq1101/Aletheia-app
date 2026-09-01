"""Loading and validating the Sprint 6 benchmark dataset.

Kept separate from `evaluation.py`: that module is arithmetic on results, this
one is the contract for the dataset itself. A malformed question — a gold page
that does not exist, an "unanswerable" question carrying gold pages, a
duplicate id — is a silent measurement error rather than a crash, so every one
of them is a load-time failure here and a test failure in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
BENCHMARK_PATH = REPO_ROOT / "datasets" / "benchmark" / "questions.json"
CORPUS_MANIFEST_PATH = REPO_ROOT / "datasets" / "corpus" / "manifest.json"

ANSWERABLE_CATEGORIES = {"fact", "method", "result", "multi-page", "cross-paper"}
UNANSWERABLE_CATEGORIES = {"unanswerable-absent", "unanswerable-domain"}
ALL_CATEGORIES = ANSWERABLE_CATEGORIES | UNANSWERABLE_CATEGORIES


class BenchmarkError(ValueError):
    """The benchmark dataset is malformed. Never downgraded to a warning."""


@dataclass(frozen=True)
class BenchmarkQuestion:
    id: str
    paper: str
    question: str
    answerable: bool
    expected_pages: list[int]
    must_contain: list[str]
    must_not_contain: list[str]
    category: str
    notes: str

    @property
    def gold(self) -> set[tuple[str, int]]:
        """Gold labels as (paper key, page number) pairs — the unit metrics use."""
        return {(self.paper, page) for page in self.expected_pages}


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or CORPUS_MANIFEST_PATH).read_text())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkError(message)


def _validate(raw: dict, known_papers: dict[str, int | None]) -> BenchmarkQuestion:
    """Validate one question. `known_papers` maps manifest key -> page count."""
    for key in (
        "id",
        "paper",
        "question",
        "answerable",
        "expected_pages",
        "must_contain",
        "must_not_contain",
        "category",
    ):
        _require(key in raw, f"question is missing required field {key!r}: {raw}")

    qid = raw["id"]
    _require(isinstance(qid, str) and bool(qid), f"id must be a non-empty string: {raw}")
    _require(
        isinstance(raw["question"], str) and raw["question"].strip().endswith("?"),
        f"{qid}: question must be a non-empty string ending in '?'",
    )
    _require(
        isinstance(raw["answerable"], bool), f"{qid}: answerable must be a boolean"
    )
    _require(
        raw["category"] in ALL_CATEGORIES,
        f"{qid}: unknown category {raw['category']!r}, expected one of "
        f"{sorted(ALL_CATEGORIES)}",
    )
    _require(
        raw["paper"] in known_papers,
        f"{qid}: paper {raw['paper']!r} is not in the corpus manifest",
    )

    pages = raw["expected_pages"]
    _require(
        isinstance(pages, list) and all(isinstance(p, int) for p in pages),
        f"{qid}: expected_pages must be a list of integers",
    )
    _require(len(set(pages)) == len(pages), f"{qid}: expected_pages has duplicates")

    for field_name in ("must_contain", "must_not_contain"):
        value = raw[field_name]
        _require(
            isinstance(value, list) and all(isinstance(t, str) and t for t in value),
            f"{qid}: {field_name} must be a list of non-empty strings",
        )

    # The consistency rules. Each of these has a specific failure mode behind
    # it, so they are checked rather than assumed.
    if raw["answerable"]:
        _require(
            raw["category"] in ANSWERABLE_CATEGORIES,
            f"{qid}: answerable question has unanswerable category "
            f"{raw['category']!r}",
        )
        _require(
            len(pages) > 0,
            f"{qid}: answerable question has no gold pages, so retrieval recall "
            "would silently score 0 for a question nothing is wrong with",
        )
        _require(
            len(raw["must_contain"]) > 0,
            f"{qid}: answerable question has no must_contain terms, so answer "
            "correctness would be unmeasurable and trivially 'correct'",
        )
    else:
        _require(
            raw["category"] in UNANSWERABLE_CATEGORIES,
            f"{qid}: unanswerable question has answerable category "
            f"{raw['category']!r}",
        )
        _require(
            not pages,
            f"{qid}: unanswerable question carries gold pages — if evidence "
            "exists for it, it is answerable",
        )
        _require(
            not raw["must_contain"],
            f"{qid}: unanswerable question carries must_contain terms",
        )

    # Range-check gold pages against the real page count recorded by
    # scripts/ingest_corpus.py. A typo'd page number is otherwise indetectable:
    # it just makes the question look like a retrieval failure forever.
    page_count = known_papers[raw["paper"]]
    if page_count is not None:
        for page in pages:
            _require(
                1 <= page <= page_count,
                f"{qid}: gold page {page} is outside {raw['paper']} "
                f"(1..{page_count})",
            )

    return BenchmarkQuestion(
        id=qid,
        paper=raw["paper"],
        question=raw["question"],
        answerable=raw["answerable"],
        expected_pages=pages,
        must_contain=raw["must_contain"],
        must_not_contain=raw["must_not_contain"],
        category=raw["category"],
        notes=raw.get("notes", ""),
    )


def load_benchmark(
    path: Path | None = None, manifest_path: Path | None = None
) -> list[BenchmarkQuestion]:
    """Load and fully validate the benchmark. Raises BenchmarkError."""
    data = json.loads((path or BENCHMARK_PATH).read_text())
    _require("questions" in data, "benchmark file has no 'questions' key")

    manifest = load_manifest(manifest_path)
    known = {p["key"]: p.get("page_count") for p in manifest["papers"]}

    questions = [_validate(raw, known) for raw in data["questions"]]

    ids = [q.id for q in questions]
    duplicates = {i for i in ids if ids.count(i) > 1}
    _require(not duplicates, f"duplicate question ids: {sorted(duplicates)}")

    return questions


__all__ = [
    "BENCHMARK_PATH",
    "BenchmarkError",
    "BenchmarkQuestion",
    "load_benchmark",
    "load_manifest",
]
