"""Evidence context builder (PRD Section 5.3).

The single most important property here: **evidence IDs are minted by the
backend**, in rank order, and handed to the model. The model never sees a chunk
id and never invents a label. `E1` means "the first block I gave you", and the
backend can always resolve it back to a real chunk -> page -> paper. A model
that cites `E9` when it was given five blocks is caught by
`answering.strip_fabricated_citations`, not trusted.

The evidence text is token-budgeted. When it does not all fit, the
lowest-ranked blocks are dropped and the count is reported to the caller — an
answer built on silently truncated evidence looks exactly like one built on
complete evidence, which is precisely the failure PRD Section 9 forbids.
"""

from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.chunking import TokenCounter
from app.services.retrieval import RetrievedChunk

log = get_logger(__name__)


@dataclass(frozen=True)
class Evidence:
    """One evidence block, with its backend-assigned ID."""

    evidence_id: str  # "E1", "E2", ...
    chunk_id: str
    paper_id: str
    paper_title: str | None
    content: str
    section: str | None
    page_number: int | None
    similarity: float
    rerank_score: float

    @property
    def location(self) -> str:
        """Human-readable citation location (PRD 5.2).

        A chunk before the first detected heading has no section, so this
        degrades to "page 7" rather than rendering "None" at the user.
        """
        page = f"page {self.page_number}" if self.page_number is not None else None
        section = f"Section {self.section}" if self.section else None
        parts = [part for part in (section, page) if part]
        return ", ".join(parts) if parts else "location unavailable"


@dataclass(frozen=True)
class BuiltContext:
    evidence: list[Evidence]
    text: str
    dropped_for_budget: int
    token_count: int

    @property
    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.evidence}


def _render_block(item: Evidence) -> str:
    """One `<EVIDENCE>` block, exactly as PRD 5.3 describes it.

    Attributes are omitted rather than emitted empty: `section="None"` would
    invite the model to cite a section that does not exist.
    """
    attributes = [f'id="{item.evidence_id}"']
    if item.paper_title:
        attributes.append(f'paper="{_escape(item.paper_title)}"')
    if item.page_number is not None:
        attributes.append(f'page="{item.page_number}"')
    if item.section:
        attributes.append(f'section="{_escape(item.section)}"')
    return f"<EVIDENCE {' '.join(attributes)}>\n{item.content.strip()}\n</EVIDENCE>"


def _escape(value: str) -> str:
    # Keeps a quote in a paper title from breaking the block's attribute list.
    return value.replace('"', "'").replace("\n", " ").strip()


def build_context(
    *,
    ranked: list[Evidence],
    counter: TokenCounter,
    max_tokens: int,
) -> BuiltContext:
    """Render ranked evidence into a token-budgeted prompt section.

    `ranked` must already be in rank order — evidence IDs are assigned by
    position, so the caller's ordering is what the model sees as "most
    relevant first".
    """
    kept: list[Evidence] = []
    blocks: list[str] = []
    used = 0

    for item in ranked:
        block = _render_block(item)
        cost = counter.count(block)
        if kept and used + cost > max_tokens:
            # Budget exhausted. Everything after this is lower-ranked, so stop
            # rather than skipping ahead to whatever happens to fit.
            break
        # The first block always goes in, even if oversized: returning zero
        # evidence for a long chunk would be worse than one over-budget block.
        kept.append(item)
        blocks.append(block)
        used += cost

    dropped = len(ranked) - len(kept)
    if dropped:
        log.warning(
            "Context budget of %d tokens dropped %d of %d evidence block(s).",
            max_tokens,
            dropped,
            len(ranked),
        )

    return BuiltContext(
        evidence=kept,
        text="\n\n".join(blocks),
        dropped_for_budget=dropped,
        token_count=used,
    )


def assign_evidence_ids(
    ranked: list[tuple[RetrievedChunk, float]],
) -> list[Evidence]:
    """Number ranked (chunk, rerank_score) pairs E1..En, best first.

    The only place in the system an evidence ID is created. IDs are positional,
    so they carry no meaning the model could guess at or extrapolate from.
    """
    return [
        Evidence(
            evidence_id=f"E{index}",
            chunk_id=str(chunk.chunk_id),
            paper_id=str(chunk.paper_id),
            paper_title=chunk.paper_title,
            content=chunk.content,
            section=chunk.section,
            page_number=chunk.page_number,
            similarity=chunk.similarity,
            rerank_score=score,
        )
        for index, (chunk, score) in enumerate(ranked, start=1)
    ]
