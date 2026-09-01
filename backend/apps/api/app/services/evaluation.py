"""Evaluation metrics for the Sprint 6 benchmark (PRD Sections 11 row 6, 12).

Every function here is pure: no database, no network, no model. That is
deliberate. A metric that can only be exercised by running the whole pipeline
cannot be unit-tested, and a benchmark whose *measuring instrument* is untested
reports numbers nobody should trust. The runner in `scripts/run_benchmark.py`
supplies the data; this module only does arithmetic on it.

The metrics answer PRD Section 12 directly:

    Retrieval   -> recall_at_k, hit_at_k, reciprocal_rank, rerank_lift
    Answering   -> answer_correctness, unanswerable handling
    Citations   -> citation_accuracy (correct page, real evidence, zero fabricated)
    Reliability -> LatencyBreakdown, per stage rather than one opaque total

**Gold labels are page-level, never chunk-level.** Chunk ids are regenerated on
every reprocess and chunk boundaries move with `CHUNK_MAX_TOKENS`, so a
chunk-keyed benchmark would be invalidated by the very 400/600/800 sweep PRD
Section 3.2 requires. A page is a stable property of the PDF.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# A term that is purely numeric (including decimals and thousands separators)
# is matched on word boundaries, so a `must_contain` of "3" does not silently
# pass on "34" or "3.57". Everything else is a case-insensitive substring.
_NUMERIC_TERM = re.compile(r"^[\d][\d,.]*$")

# Sentence split good enough to spot an uncited claim. Deliberately crude: it
# only has to segment prose, and a wrong split changes a diagnostic ratio
# rather than a pass/fail.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# An evidence marker as the backend mints them: [E1] or [E1, E3].
_CITATION_MARKER = re.compile(r"\[[^\[\]]*?E\d+[^\[\]]*?\]")


@dataclass(frozen=True)
class PageRef:
    """One retrieved chunk reduced to the unit gold labels are written in."""

    paper: str
    page: int | None

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        return f"{self.paper}:p{self.page}"


# --- term matching -----------------------------------------------------------


def term_matches(term: str, text: str) -> bool:
    """Is `term` present in `text`?

    Numeric terms match on word boundaries; everything else is a
    case-insensitive substring. Without the numeric rule a one-character gold
    term like "3" matches almost any answer containing a number, and the
    correctness metric quietly inflates.
    """
    if not term:
        return False
    if _NUMERIC_TERM.match(term):
        # Guarded on both sides. The trailing `(?!\.\d)` is the subtle one: it
        # stops a term of "3" matching the "3" in "3.57", which would make
        # every short numeric expectation nearly free to satisfy. A trailing
        # full stop that ends a sentence is still fine, since only a dot
        # *followed by a digit* is rejected.
        pattern = rf"(?<![\d.]){re.escape(term)}(?!\d)(?!\.\d)"
        return re.search(pattern, text) is not None
    return term.casefold() in text.casefold()


def terms_present(terms: list[str], text: str) -> list[str]:
    return [term for term in terms if term_matches(term, text)]


def terms_missing(terms: list[str], text: str) -> list[str]:
    return [term for term in terms if not term_matches(term, text)]


# --- retrieval ---------------------------------------------------------------


def _gold_hits(retrieved: list[PageRef], gold: set[tuple[str, int]]) -> list[int]:
    """0-based ranks at which a gold page appears."""
    return [
        rank
        for rank, ref in enumerate(retrieved)
        if ref.page is not None and (ref.paper, ref.page) in gold
    ]


def hit_at_k(retrieved: list[PageRef], gold: set[tuple[str, int]], k: int) -> float:
    """1.0 if any gold page is in the top k, else 0.0.

    Returns 0.0 when there is no gold to find, rather than the vacuous 1.0 that
    "all zero of the gold pages were retrieved" would otherwise give. An
    unanswerable question has no retrieval score, and the runner excludes it.
    """
    if not gold or k < 1:
        return 0.0
    return 1.0 if any(rank < k for rank in _gold_hits(retrieved, gold)) else 0.0


def recall_at_k(retrieved: list[PageRef], gold: set[tuple[str, int]], k: int) -> float:
    """Fraction of DISTINCT gold pages appearing in the top k.

    Distinct matters: three retrieved chunks from the same gold page is one
    page found, not three. Counting chunks would make recall rise with chunk
    size, which is precisely the variable PRD Section 3.2 wants to compare.
    """
    if not gold or k < 1:
        return 0.0
    found = {
        (ref.paper, ref.page)
        for ref in retrieved[:k]
        if ref.page is not None and (ref.paper, ref.page) in gold
    }
    return len(found) / len(gold)


def reciprocal_rank(retrieved: list[PageRef], gold: set[tuple[str, int]]) -> float:
    """1 / (rank of the first gold page), 1-based. 0.0 if never retrieved."""
    if not gold:
        return 0.0
    hits = _gold_hits(retrieved, gold)
    return 1.0 / (hits[0] + 1) if hits else 0.0


def rerank_lift(
    *,
    before: list[PageRef],
    after: list[PageRef],
    gold: set[tuple[str, int]],
    k: int,
) -> dict[str, float]:
    """How much reranking changed retrieval quality, at equal k.

    Compared at the same k on purpose. Reranking that only ever narrows 20
    candidates to 6 would show a "gain" from the smaller denominator alone;
    holding k fixed measures reordering, which is the thing the stage claims
    to do.
    """
    return {
        "recall_before": recall_at_k(before, gold, k),
        "recall_after": recall_at_k(after, gold, k),
        "recall_lift": recall_at_k(after, gold, k) - recall_at_k(before, gold, k),
        "mrr_before": reciprocal_rank(before, gold),
        "mrr_after": reciprocal_rank(after, gold),
        "mrr_lift": reciprocal_rank(after, gold) - reciprocal_rank(before, gold),
    }


# --- answering ---------------------------------------------------------------


@dataclass(frozen=True)
class CorrectnessResult:
    correct: bool
    keyword_recall: float
    matched: list[str]
    missing: list[str]
    forbidden_present: list[str]


def answer_correctness(
    *, answer: str, must_contain: list[str], must_not_contain: list[str]
) -> CorrectnessResult:
    """Deterministic correctness: every required term present, none forbidden.

    Weaker per question than an LLM judge, and chosen anyway: a judge would put
    a second unverified model inside the measurement and charge per run. The
    compensation is question count, and `keyword_recall` keeps partial credit
    visible so a near-miss is distinguishable from a total miss.
    """
    matched = terms_present(must_contain, answer)
    missing = terms_missing(must_contain, answer)
    forbidden = terms_present(must_not_contain, answer)
    recall = len(matched) / len(must_contain) if must_contain else 0.0
    return CorrectnessResult(
        correct=not missing and not forbidden,
        keyword_recall=recall,
        matched=matched,
        missing=missing,
        forbidden_present=forbidden,
    )


def evidence_sufficiency(*, evidence_text: str, must_contain: list[str]) -> bool:
    """Does the evidence handed to the model actually contain the answer?

    The single most useful diagnostic in the suite, and it needs no LLM. It
    separates the two failure modes that a bare correctness score fuses
    together: retrieval never surfaced the answer, versus the model was given
    the answer and did not use it. The mean over the benchmark is the **ceiling
    on answer correctness** — no model, however good, can exceed it while
    obeying the grounding rules in PRD Section 5.4.

    Measured on the assembled evidence rather than on pages, because this is
    the text the model actually sees. A question can have its gold page
    retrieved while the specific chunk carrying the number is a neighbouring
    table — page-level gold cannot see that difference, and this can.
    """
    return not terms_missing(must_contain, evidence_text)


def handled_unanswerable(*, sufficient_evidence: bool) -> bool:
    """PRD 5.4 / 12: the system must explicitly qualify what it cannot answer.

    A correct refusal is `sufficient_evidence: false`. Note this is a
    *successful* answer, not an error — treating it as a failure elsewhere
    would defeat the guarantee it exists to provide.
    """
    return sufficient_evidence is False


# --- citations ---------------------------------------------------------------


@dataclass(frozen=True)
class CitationCheck:
    """One citation reduced to what PRD Section 12 requires of it."""

    paper: str | None
    page: int | None
    resolves: bool  # points at a real chunk -> page -> paper


@dataclass(frozen=True)
class CitationResult:
    total: int
    resolvable: int
    on_gold_page: int
    precision: float  # of the citations made, how many landed on a gold page
    fabricated_removed: int
    zero_fabricated: bool


def citation_accuracy(
    *,
    citations: list[CitationCheck],
    gold: set[tuple[str, int]],
    fabricated_removed: int,
) -> CitationResult:
    """Do the citations point at real evidence, on the right page?

    `zero_fabricated` is the pass/fail PRD Section 12 actually names. It is
    reported separately from precision because they fail for different reasons:
    a fabricated ID is a grounding failure, while a citation on the wrong real
    page is a retrieval or attribution failure.
    """
    total = len(citations)
    resolvable = sum(1 for c in citations if c.resolves)
    on_gold = sum(
        1
        for c in citations
        if c.paper is not None
        and c.page is not None
        and (c.paper, c.page) in gold
    )
    return CitationResult(
        total=total,
        resolvable=resolvable,
        on_gold_page=on_gold,
        precision=(on_gold / total) if total else 0.0,
        fabricated_removed=fabricated_removed,
        zero_fabricated=fabricated_removed == 0,
    )


def uncited_claim_ratio(answer: str, *, min_words: int = 6) -> float:
    """Fraction of substantive sentences carrying no evidence marker.

    A faithfulness *smell*, not a verdict: a sentence can legitimately restate
    the question or introduce the answer without citing. Short sentences are
    skipped for that reason. Reported as a diagnostic so a confident,
    uncited-prose answer is visible rather than scoring the same as a
    well-cited one.
    """
    sentences = [s.strip() for s in _SENTENCE.split(answer.strip()) if s.strip()]
    substantive = [s for s in sentences if len(s.split()) >= min_words]
    if not substantive:
        return 0.0
    uncited = sum(1 for s in substantive if not _CITATION_MARKER.search(s))
    return uncited / len(substantive)


# --- latency -----------------------------------------------------------------


@dataclass
class LatencyBreakdown:
    """Per-stage timings in milliseconds.

    Broken out rather than reported as one total: "answering took 9 seconds" is
    not diagnosable, and the stages have completely different cost profiles —
    embedding and reranking are local model work, the LLM call is a network
    round trip billed per token.
    """

    retrieve_ms: float = 0.0
    rerank_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "retrieve_ms": round(self.retrieve_ms, 1),
            "rerank_ms": round(self.rerank_ms, 1),
            "llm_ms": round(self.llm_ms, 1),
            "total_ms": round(self.total_ms, 1),
        }


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. Returns 0.0 for an empty sample.

    Nearest-rank rather than interpolated so every reported latency is a real
    measurement that actually occurred, not an average of two runs.
    """
    if not values:
        return 0.0
    if not 0 < p <= 100:
        raise ValueError(f"percentile must be in (0, 100], got {p}")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(p / 100 * len(ordered))))
    return ordered[rank - 1]


# --- aggregation -------------------------------------------------------------


@dataclass
class MetricAccumulator:
    """Running mean of a named metric, tolerant of questions that skip it."""

    name: str
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.values.append(value)

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0

    @property
    def count(self) -> int:
        return len(self.values)


__all__ = [
    "CitationCheck",
    "CitationResult",
    "CorrectnessResult",
    "LatencyBreakdown",
    "MetricAccumulator",
    "PageRef",
    "answer_correctness",
    "citation_accuracy",
    "evidence_sufficiency",
    "handled_unanswerable",
    "hit_at_k",
    "percentile",
    "recall_at_k",
    "reciprocal_rank",
    "rerank_lift",
    "term_matches",
    "terms_missing",
    "terms_present",
    "uncited_claim_ratio",
]
