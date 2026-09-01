"""The benchmark dataset has to be trustworthy before it can measure anything.

Two kinds of check live here:

1. **Schema and consistency** — a malformed question is a silent measurement
   error, not a crash. An "unanswerable" question carrying gold pages, or an
   answerable one with no `must_contain` terms, would score perfectly forever
   while measuring nothing.

2. **Gold labels against the real corpus** — the important one. The failure
   this sprint had to avoid is a benchmark written from memory of these
   papers: questions that sound right, gold pages assigned by recollection,
   and a green report that measures nothing but its author's self-consistency.
   So every `must_contain` term is checked to actually appear in the text
   **this pipeline extracted** from the gold pages, using the pipeline's own
   parser. A question whose gold page does not contain its own answer fails
   the suite.

The corpus PDFs are gitignored (reproduce with `scripts/fetch_corpus.py`), so
the corpus-dependent tests skip cleanly rather than failing when it is absent.
The schema tests always run.
"""

import json
from collections import Counter

import pytest

from app.services.benchmark import (
    ANSWERABLE_CATEGORIES,
    UNANSWERABLE_CATEGORIES,
    BenchmarkError,
    load_benchmark,
    load_manifest,
)
from app.services.evaluation import terms_missing
from app.services.parsing import build_parser

CORPUS_DIR = None  # resolved in the fixture below


@pytest.fixture(scope="session")
def benchmark():
    return load_benchmark()


@pytest.fixture(scope="session")
def manifest():
    return load_manifest()


@pytest.fixture(scope="session")
def corpus_pages(manifest):
    """{(paper_key, page_number): cleaned_text} straight from the parser.

    Parsed rather than read from the database on purpose: this asserts a
    property of the *dataset against the corpus*, so it must not depend on a
    particular machine having ingested it. The parser is the same one
    ingestion uses, so what is checked is what the pipeline really sees.
    """
    from app.services.benchmark import REPO_ROOT

    pdf_dir = REPO_ROOT / "datasets" / "corpus" / "pdfs"
    missing = [
        p["key"] for p in manifest["papers"] if not (pdf_dir / f"{p['key']}.pdf").exists()
    ]
    if missing:
        pytest.skip(
            f"benchmark corpus not fetched (missing {', '.join(missing)}); "
            "run scripts/fetch_corpus.py"
        )

    parser = build_parser()
    pages: dict[tuple[str, int], str] = {}
    for paper in manifest["papers"]:
        key = paper["key"]
        parsed = parser.parse(data=(pdf_dir / f"{key}.pdf").read_bytes())
        for page in parsed.pages:
            pages[(key, page.page_number)] = page.cleaned_text
    return pages


# --- shape -------------------------------------------------------------------


def test_benchmark_loads_and_validates(benchmark):
    assert benchmark, "benchmark is empty"


def test_benchmark_matches_the_prd_scale(benchmark):
    """PRD Section 11 sprint 6: '~10 papers x 15 questions'."""
    per_paper = Counter(q.paper for q in benchmark)
    assert len(per_paper) == 10, f"expected 10 papers, got {sorted(per_paper)}"
    assert set(per_paper.values()) == {15}, f"uneven question counts: {per_paper}"
    assert len(benchmark) == 150


def test_question_ids_are_unique(benchmark):
    ids = [q.id for q in benchmark]
    assert len(set(ids)) == len(ids)


def test_every_paper_has_unanswerable_questions(benchmark):
    """PRD Section 12 requires the system to qualify unanswerable questions.
    Concentrating those in one paper would let a system pass by learning
    'decline anything about paper X'."""
    by_paper = Counter(q.paper for q in benchmark if not q.answerable)
    assert len(by_paper) == 10, f"papers with no unanswerable question: {by_paper}"


def test_unanswerable_share_is_substantial_but_not_dominant(benchmark):
    share = sum(1 for q in benchmark if not q.answerable) / len(benchmark)
    assert 0.1 <= share <= 0.35, f"unanswerable share is {share:.0%}"


def test_categories_are_consistent_with_answerability(benchmark):
    for q in benchmark:
        expected = ANSWERABLE_CATEGORIES if q.answerable else UNANSWERABLE_CATEGORIES
        assert q.category in expected, f"{q.id}: category/answerable mismatch"


def test_answerable_questions_carry_gold_and_expectations(benchmark):
    for q in benchmark:
        if q.answerable:
            assert q.expected_pages, f"{q.id} has no gold pages"
            assert q.must_contain, f"{q.id} has no must_contain terms"


def test_unanswerable_questions_carry_no_gold(benchmark):
    """If evidence exists for it, it is answerable — the label is then wrong."""
    for q in benchmark:
        if not q.answerable:
            assert not q.expected_pages, f"{q.id} is unanswerable but has gold pages"
            assert not q.must_contain, f"{q.id} is unanswerable but has must_contain"


def test_every_question_has_notes_explaining_its_label(benchmark):
    for q in benchmark:
        assert q.notes.strip(), f"{q.id} has no notes justifying its gold label"


# --- the schema is enforced, not merely documented ---------------------------


def _write(tmp_path, questions):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"questions": questions}))
    return path


def _valid_question(**overrides):
    base = {
        "id": "resnet-99",
        "paper": "resnet",
        "question": "What momentum was used?",
        "answerable": True,
        "expected_pages": [4],
        "must_contain": ["0.9"],
        "must_not_contain": [],
        "category": "method",
        "notes": "test fixture",
    }
    base.update(overrides)
    return base


def test_unanswerable_question_with_gold_pages_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        [
            _valid_question(
                answerable=False,
                category="unanswerable-absent",
                expected_pages=[4],
                must_contain=[],
            )
        ],
    )
    with pytest.raises(BenchmarkError, match="carries gold pages"):
        load_benchmark(path)


def test_answerable_question_without_gold_pages_is_rejected(tmp_path):
    path = _write(tmp_path, [_valid_question(expected_pages=[])])
    with pytest.raises(BenchmarkError, match="no gold pages"):
        load_benchmark(path)


def test_answerable_question_without_must_contain_is_rejected(tmp_path):
    path = _write(tmp_path, [_valid_question(must_contain=[])])
    with pytest.raises(BenchmarkError, match="no must_contain"):
        load_benchmark(path)


def test_unknown_paper_is_rejected(tmp_path):
    path = _write(tmp_path, [_valid_question(paper="not-a-real-paper")])
    with pytest.raises(BenchmarkError, match="not in the corpus manifest"):
        load_benchmark(path)


def test_gold_page_outside_the_paper_is_rejected(tmp_path):
    """A typo'd page number is otherwise undetectable — it just makes the
    question look like a permanent retrieval failure."""
    path = _write(tmp_path, [_valid_question(expected_pages=[9999])])
    with pytest.raises(BenchmarkError, match="outside resnet"):
        load_benchmark(path)


def test_duplicate_ids_are_rejected(tmp_path):
    path = _write(tmp_path, [_valid_question(), _valid_question()])
    with pytest.raises(BenchmarkError, match="duplicate question ids"):
        load_benchmark(path)


def test_unknown_category_is_rejected(tmp_path):
    path = _write(tmp_path, [_valid_question(category="vibes")])
    with pytest.raises(BenchmarkError, match="unknown category"):
        load_benchmark(path)


def test_missing_required_field_is_rejected(tmp_path):
    question = _valid_question()
    del question["expected_pages"]
    path = _write(tmp_path, [question])
    with pytest.raises(BenchmarkError, match="missing required field"):
        load_benchmark(path)


# --- gold labels vs. the real corpus (the anti-self-grading check) -----------


def test_gold_pages_actually_contain_the_expected_answers(benchmark, corpus_pages):
    """Every must_contain term must appear in the extracted text of that
    question's own gold pages.

    This is what stops the benchmark from grading itself. A question written
    from recollection rather than from the extracted text fails here, loudly,
    naming the terms it could not find.
    """
    failures = []
    for q in benchmark:
        if not q.answerable:
            continue
        text = "\n".join(corpus_pages.get((q.paper, p), "") for p in q.expected_pages)
        if not text.strip():
            failures.append(f"{q.id}: gold pages {q.expected_pages} have no text")
            continue
        missing = terms_missing(q.must_contain, text)
        if missing:
            failures.append(
                f"{q.id}: {missing} absent from {q.paper} pages {q.expected_pages}"
            )
    assert not failures, "gold labels not supported by the corpus:\n" + "\n".join(
        failures
    )


def test_every_gold_page_was_extracted_with_real_content(benchmark, corpus_pages):
    """A gold page that extracted to nothing (a full-page figure, say) makes a
    question unanswerable in practice while still being labelled answerable."""
    thin = [
        f"{q.id}: {q.paper} p{page} extracted {len(corpus_pages.get((q.paper, page), ''))} chars"
        for q in benchmark
        if q.answerable
        for page in q.expected_pages
        if len(corpus_pages.get((q.paper, page), "")) < 200
    ]
    assert not thin, "gold pages with little or no extracted text:\n" + "\n".join(thin)


def test_corpus_manifest_records_page_counts(manifest):
    """Written back by scripts/ingest_corpus.py. Without them, gold pages
    cannot be range-checked."""
    for paper in manifest["papers"]:
        assert paper.get("page_count"), f"{paper['key']} has no recorded page_count"
        assert paper.get("sha256"), f"{paper['key']} is not pinned by SHA-256"


def test_manifest_page_counts_match_the_pdfs(manifest, corpus_pages):
    for paper in manifest["papers"]:
        key = paper["key"]
        actual = sum(1 for (paper_key, _) in corpus_pages if paper_key == key)
        assert actual == paper["page_count"], (
            f"{key}: manifest says {paper['page_count']} pages, parser found {actual}"
        )
