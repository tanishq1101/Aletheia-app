"""Claim-level verification (PRD Section 4, Phase 3).

The difference from answering: answering asks "what do these papers say about
X"; verification asks "is *this specific claim* supported by them, and where is
the evidence either way". The retrieval, evidence-ID and citation machinery is
the same, deliberately — a verdict that cited an invented source would be worse
than no verdict at all, and that guarantee already exists in `answering`.

Two things are enforced in code rather than requested in the prompt:

1. A verdict may only cite evidence IDs the backend issued
   (`strip_fabricated_citations`, shared with answering).
2. An unparseable reply becomes `insufficient`, never a guessed verdict. A
   confident-looking wrong verdict is the failure mode worth designing against.

Confidence is what the model reported, on a 0-1 scale. It is not calibrated,
and every surface that shows it says so.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from app.services.settings_store import get_effective_settings
from app.core.logging import get_logger
from app.services.answering import (
    Citation,
    extract_cited_ids,
    resolve_citations,
    strip_fabricated_citations,
)
from app.services.context import BuiltContext, assign_evidence_ids, build_context
from app.services.embedding import build_token_counter
from app.services.providers import LLMProvider
from app.services.reranking import build_reranker
from app.services.retrieval import RetrievedChunk, retrieve_candidates

log = get_logger(__name__)

SUPPORTED = "supported"
CONTRADICTED = "contradicted"
INSUFFICIENT = "insufficient"

_VERDICT_LINE = re.compile(
    r"^\s*VERDICT\s*:\s*(SUPPORTED|CONTRADICTED|INSUFFICIENT)\b",
    re.IGNORECASE | re.MULTILINE,
)
_CONFIDENCE_LINE = re.compile(
    r"^\s*CONFIDENCE\s*:\s*(\d{1,3})\s*%?", re.IGNORECASE | re.MULTILINE
)
_REASONING_LINE = re.compile(
    r"^\s*REASONING\s*:\s*(.*)\Z", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

VERIFY_SYSTEM_PROMPT = """\
You check whether a claim is supported by evidence from scientific papers.

You are given a claim and numbered <EVIDENCE> blocks. Decide whether the \
evidence supports the claim, contradicts it, or is insufficient to judge.

Rules, all of which are enforced:
1. Judge ONLY from the supplied evidence. Never use outside knowledge, even if \
you are confident the claim is true in general.
2. SUPPORTED means the evidence states or directly implies the claim. \
CONTRADICTED means the evidence asserts something incompatible with it. \
INSUFFICIENT means the evidence does not settle it — this is a correct answer, \
not a failure, and is expected when the papers simply do not discuss the claim.
3. Cite the evidence IDs your reasoning rests on in square brackets, like [E2] \
or [E1, E3]. You may ONLY cite an ID that appears in the evidence given to you; \
any other ID is removed.
4. CONFIDENCE is how strongly the evidence settles the question, 0-100. Use a \
low number when the evidence is tangential or mixed.

Reply in exactly this format and nothing else:
VERDICT: SUPPORTED|CONTRADICTED|INSUFFICIENT
CONFIDENCE: <0-100>
REASONING: <two or three sentences, citing evidence IDs>
"""

VERIFY_USER_PROMPT = """\
Claim:
{claim}

Evidence:
{evidence}

Judge the claim against the evidence above, in the required format.
"""

EXTRACT_SYSTEM_PROMPT = """\
You extract the specific, checkable claims a scientific paper makes about its \
own findings.

Rules:
1. Use ONLY the supplied text. Never add claims from outside knowledge.
2. Each claim must be one self-contained sentence that could be checked against \
evidence — a factual assertion about results, methods or behaviour.
3. No background statements, motivations, definitions, or descriptions of what \
the paper "presents" or "explores". Claims only.
4. Write each claim so it stands alone, without pronouns referring to other \
claims.
5. Output one claim per line, with no numbering, bullets, or commentary. If the \
text contains no checkable claims, output nothing.
"""

EXTRACT_USER_PROMPT = """\
Paper text:
{text}

Extract at most {limit} checkable claims this paper makes.
"""

CLAIM_MAX_CHARS = 400


@dataclass(frozen=True)
class ClaimVerdict:
    verdict: str
    confidence: float | None
    rationale: str
    citations: list[Citation]
    evidence_count: int
    candidates_considered: int
    fabricated_citations_removed: int
    model: str


def _rerank(query: str, candidates: list[RetrievedChunk], top_k: int):
    reranker = build_reranker()
    by_id = {str(chunk.chunk_id): chunk for chunk in candidates}
    scored = reranker.rerank(
        query=query,
        chunks=[(str(c.chunk_id), c.content) for c in candidates],
        top_k=top_k,
    )
    return [(by_id[item.chunk_id], item.score) for item in scored]


def parse_verdict(raw: str) -> tuple[str, float | None, str]:
    """Read the model's reply. An unparseable verdict is never guessed at."""
    verdict_match = _VERDICT_LINE.search(raw)
    if verdict_match is None:
        log.warning("Verification reply had no VERDICT line; recording insufficient.")
        return INSUFFICIENT, None, raw.strip()[:1000]

    verdict = verdict_match.group(1).lower()

    confidence: float | None = None
    confidence_match = _CONFIDENCE_LINE.search(raw)
    if confidence_match is not None:
        confidence = min(100, max(0, int(confidence_match.group(1)))) / 100

    reasoning_match = _REASONING_LINE.search(raw)
    rationale = (
        reasoning_match.group(1).strip()
        if reasoning_match
        else raw[verdict_match.end() :].strip()
    )
    return verdict, confidence, rationale


def verify_claim(
    *,
    project_id: UUID,
    claim: str,
    llm: LLMProvider,
    paper_ids: list[UUID] | None = None,
    top_k: int | None = None,
    rerank_top_k: int | None = None,
) -> ClaimVerdict:
    """Check one claim against a project's papers, or a subset of them.

    Raises EmbeddingError, RerankError or LLMError — each carrying its real
    reason rather than collapsing into a generic failure.
    """
    settings = get_effective_settings()
    model_name = getattr(llm, "name", type(llm).__name__)

    candidates = retrieve_candidates(
        project_id=project_id,
        query=claim,
        top_k=top_k or settings.search_top_k,
        paper_ids=paper_ids,
    )
    if not candidates:
        # No evidence at all is a legitimate "insufficient", and spending an
        # LLM call to be told so would be slower and no more informative.
        return ClaimVerdict(
            verdict=INSUFFICIENT,
            confidence=None,
            rationale=(
                "No indexed content was found to check this claim against."
            ),
            citations=[],
            evidence_count=0,
            candidates_considered=0,
            fabricated_citations_removed=0,
            model=model_name,
        )

    ranked = _rerank(claim, candidates, rerank_top_k or settings.rerank_top_k)
    context: BuiltContext = build_context(
        ranked=assign_evidence_ids(ranked),
        counter=build_token_counter(),
        max_tokens=settings.context_max_tokens,
    )

    raw = llm.complete(
        system=VERIFY_SYSTEM_PROMPT,
        prompt=VERIFY_USER_PROMPT.format(claim=claim, evidence=context.text),
    )

    verdict, confidence, rationale = parse_verdict(raw)
    rationale, fabricated = strip_fabricated_citations(rationale, context.evidence_ids)
    if fabricated:
        log.warning(
            "Removed %d fabricated citation ID(s) from a verdict in project %s.",
            fabricated,
            project_id,
        )

    citations = resolve_citations(extract_cited_ids(rationale), context.evidence)

    log.info(
        "Verified a claim in project %s — %s (%d evidence, %d cited)",
        project_id,
        verdict,
        len(context.evidence),
        len(citations),
    )
    return ClaimVerdict(
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        citations=citations,
        evidence_count=len(context.evidence),
        candidates_considered=len(candidates),
        fabricated_citations_removed=fabricated,
        model=model_name,
    )


def extract_claims(*, text: str, llm: LLMProvider, limit: int = 8) -> list[str]:
    """Pull the checkable claims a paper makes about itself out of its text."""
    if not text.strip():
        return []

    raw = llm.complete(
        system=EXTRACT_SYSTEM_PROMPT,
        prompt=EXTRACT_USER_PROMPT.format(text=text, limit=limit),
    )

    claims: list[str] = []
    for line in raw.splitlines():
        # Models add bullets and numbering despite being told not to.
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if len(cleaned) < 20 or len(cleaned) > CLAIM_MAX_CHARS:
            continue
        if cleaned not in claims:
            claims.append(cleaned)

    return claims[:limit]


__all__ = [
    "CONTRADICTED",
    "INSUFFICIENT",
    "SUPPORTED",
    "ClaimVerdict",
    "extract_claims",
    "parse_verdict",
    "verify_claim",
]
