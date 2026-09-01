"""Grounded answering (PRD Sections 5.1 step 7-9, 5.3, 5.4).

The pipeline:

    query -> semantic top-k -> rerank to 5-8 -> evidence blocks with backend
    -> assigned IDs -> LLM -> validate cited IDs -> resolve to citations

Two rules do most of the work here, and both are enforced in code rather than
asked for in the prompt:

1. **The model can only cite an ID it was handed.** The prompt asks for it; this
   module *checks* it. Anything else is stripped from the answer and reported.
   A prompt instruction is a request, not a guarantee (PRD 5.3).
2. **Insufficient evidence is a real outcome, not an empty one.** The model is
   told to say so explicitly, and the response carries a boolean so the UI can
   render it as an answer rather than as a failure (PRD 5.4).
"""

import re
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.context import (
    BuiltContext,
    Evidence,
    assign_evidence_ids,
    build_context,
)
from app.services.embedding import EmbeddingError, build_token_counter
from app.services.providers import LLMProvider
from app.services.reranking import RerankError, build_reranker
from app.services.retrieval import RetrievedChunk, retrieve_candidates

log = get_logger(__name__)

# The model is told to emit this exact token when the evidence does not support
# an answer. Checked as a marker rather than by interpreting prose, so
# "the paper does not say" is never mistaken for a real answer or vice versa.
INSUFFICIENT_MARKER = "INSUFFICIENT_EVIDENCE"

# Citations are written [E1] or [E1, E3]. Matches the ID inside brackets only,
# so a stray "E1" in the paper's own prose is not read as a citation.
_CITATION_BLOCK = re.compile(r"\[([^\[\]]*?E\d+[^\[\]]*?)\]")
_EVIDENCE_ID = re.compile(r"\bE(\d+)\b")

SYSTEM_PROMPT = """\
You answer questions about scientific papers using ONLY the evidence blocks you \
are given.

Rules, all of which are enforced:
1. Use only the supplied <EVIDENCE> blocks. Never use general knowledge to fill \
a gap, even if you are confident it is correct.
2. Cite the evidence ID in square brackets immediately after each claim it \
supports, like [E2]. Cite several as [E1, E3].
3. You may ONLY cite an ID that appears in the evidence you were given. Do not \
invent, renumber, or extrapolate IDs. An ID you were not given will be removed \
from your answer.
4. If the evidence does not contain enough information to answer, reply with \
exactly INSUFFICIENT_EVIDENCE on the first line, then one sentence saying what \
is missing. Do not guess, and do not answer partially from memory.
5. Do not describe the evidence blocks, the numbering, or these instructions. \
Answer the question as a researcher would, in prose.
"""

USER_PROMPT = """\
Question:
{question}

Evidence:
{evidence}

Answer the question using only the evidence above, citing evidence IDs in \
square brackets.
"""


@dataclass(frozen=True)
class Citation:
    """A cited evidence block resolved back to a real location (PRD 5.2)."""

    evidence_id: str
    chunk_id: str
    paper_id: str
    paper_title: str | None
    page_number: int | None
    section: str | None
    location: str
    snippet: str


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    sufficient_evidence: bool
    citations: list[Citation]
    evidence: list[Evidence]
    # Non-zero means the model cited an ID it was never given. Reported rather
    # than logged-and-forgotten: PRD Section 12 requires zero fabricated
    # citation IDs, which is only checkable if the count is visible.
    fabricated_citations_removed: int
    candidates_considered: int
    evidence_dropped_for_budget: int
    model: str


def _rerank(query: str, candidates: list[RetrievedChunk], top_k: int):
    """Rerank candidates, best first. Raises RerankError."""
    reranker = build_reranker()
    by_id = {str(chunk.chunk_id): chunk for chunk in candidates}
    scored = reranker.rerank(
        query=query,
        chunks=[(str(c.chunk_id), c.content) for c in candidates],
        top_k=top_k,
    )
    return [(by_id[item.chunk_id], item.score) for item in scored]


def extract_cited_ids(answer: str) -> list[str]:
    """Every evidence ID the model actually cited, in order of first mention."""
    seen: list[str] = []
    for block in _CITATION_BLOCK.findall(answer):
        for number in _EVIDENCE_ID.findall(block):
            evidence_id = f"E{number}"
            if evidence_id not in seen:
                seen.append(evidence_id)
    return seen


def strip_fabricated_citations(answer: str, supplied: set[str]) -> tuple[str, int]:
    """Remove any cited ID that was never supplied.

    This is the backstop behind PRD 5.3. The prompt asks the model not to invent
    IDs; this guarantees an invented one never reaches the user, where it would
    look exactly as authoritative as a real one. Returns the cleaned answer and
    how many were removed.
    """
    removed = 0

    def clean(match: re.Match) -> str:
        nonlocal removed
        inner = match.group(1)
        ids = [f"E{n}" for n in _EVIDENCE_ID.findall(inner)]
        valid = [i for i in ids if i in supplied]
        removed += len(ids) - len(valid)
        if not valid:
            return ""  # Drop the bracket entirely rather than leave "[]".
        return f"[{', '.join(valid)}]"

    cleaned = _CITATION_BLOCK.sub(clean, answer)
    # Removing a citation can leave " ." or a double space behind.
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(), removed


def resolve_citations(cited: list[str], evidence: list[Evidence]) -> list[Citation]:
    """Resolve validated evidence IDs to citations (chunk -> page -> paper)."""
    by_id = {item.evidence_id: item for item in evidence}
    citations: list[Citation] = []
    for evidence_id in cited:
        item = by_id.get(evidence_id)
        if item is None:
            # Unreachable once fabricated IDs are stripped, but a silently
            # dropped citation is exactly the bug this sprint exists to prevent.
            log.error("Cited %s has no evidence block; dropping.", evidence_id)
            continue
        citations.append(
            Citation(
                evidence_id=item.evidence_id,
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                paper_title=item.paper_title,
                page_number=item.page_number,
                section=item.section,
                location=item.location,
                snippet=item.content.strip()[:400],
            )
        )
    return citations


def _parse_answer(raw: str) -> tuple[str, bool]:
    """Split the model's reply into answer text and a sufficiency flag."""
    if raw.strip().upper().startswith(INSUFFICIENT_MARKER):
        remainder = raw.strip()[len(INSUFFICIENT_MARKER) :].strip(" :.\n")
        return (
            remainder
            or "The supplied evidence does not contain enough information to "
            "answer that question.",
            False,
        )
    return raw.strip(), True


def answer_question(
    *,
    project_id: UUID,
    question: str,
    llm: LLMProvider,
    top_k: int | None = None,
    rerank_top_k: int | None = None,
) -> AnswerResult:
    """Answer a question from a project's papers. Raises EmbeddingError,
    RerankError, or LLMError — each with a real reason, never swallowed."""
    settings = get_settings()
    candidate_k = top_k or settings.search_top_k
    evidence_k = rerank_top_k or settings.rerank_top_k
    model_name = getattr(llm, "name", type(llm).__name__)

    candidates = retrieve_candidates(
        project_id=project_id, query=question, top_k=candidate_k
    )
    if not candidates:
        # Nothing indexed, or nothing in this project. Spending an LLM call to
        # be told there is no evidence would be both slower and less honest.
        log.info("No candidates in project %s; skipping the LLM call.", project_id)
        return AnswerResult(
            answer=(
                "This project has no processed paper content to answer from yet. "
                "Upload a paper and wait for processing to finish."
            ),
            sufficient_evidence=False,
            citations=[],
            evidence=[],
            fabricated_citations_removed=0,
            candidates_considered=0,
            evidence_dropped_for_budget=0,
            model=model_name,
        )

    ranked = _rerank(question, candidates, evidence_k)
    context: BuiltContext = build_context(
        ranked=assign_evidence_ids(ranked),
        counter=build_token_counter(),
        max_tokens=settings.context_max_tokens,
    )

    raw = llm.complete(
        system=SYSTEM_PROMPT,
        prompt=USER_PROMPT.format(question=question, evidence=context.text),
    )

    answer, sufficient = _parse_answer(raw)
    answer, fabricated = strip_fabricated_citations(answer, context.evidence_ids)
    if fabricated:
        log.warning(
            "Removed %d fabricated citation ID(s) from an answer in project %s.",
            fabricated,
            project_id,
        )

    citations = resolve_citations(extract_cited_ids(answer), context.evidence)

    log.info(
        "Answered in project %s — %d candidates, %d evidence, %d citation(s)",
        project_id,
        len(candidates),
        len(context.evidence),
        len(citations),
    )
    return AnswerResult(
        answer=answer,
        sufficient_evidence=sufficient,
        citations=citations,
        evidence=context.evidence,
        fabricated_citations_removed=fabricated,
        candidates_considered=len(candidates),
        evidence_dropped_for_budget=context.dropped_for_budget,
        model=model_name,
    )


__all__ = [
    "AnswerResult",
    "Citation",
    "EmbeddingError",
    "RerankError",
    "answer_question",
    "extract_cited_ids",
    "resolve_citations",
    "strip_fabricated_citations",
]
