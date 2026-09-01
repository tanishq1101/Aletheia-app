"""Section- and paragraph-aware chunking (PRD Sprint 3).

Chunks are token-bounded with overlap, and are built from the *normalized* page
text so paragraph breaks are available as natural boundaries. Sprint 2's
normalization ordering is what makes those breaks exist — see PROGRESS.md.

Chunk size is a parameter, not a constant: PRD Section 3.2 commits to
benchmarking 400 / 600 / 800 tokens rather than assuming one.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from app.services.providers import DetectedSection, ParsedPage

# Defaults. 600 sits in the middle of the range Section 3.2 will benchmark;
# it is a starting point, not a finding.
DEFAULT_CHUNK_TOKENS = 600
DEFAULT_OVERLAP_TOKENS = 80

_PARAGRAPH = re.compile(r"\n\s*\n")
# Sentence end followed by whitespace. Used only to split paragraphs that are
# themselves larger than one chunk.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class TokenCounter(Protocol):
    """Counts tokens the way the embedding model counts them."""

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    content: str
    token_count: int
    page_number: int
    section: str | None
    start_offset: int
    end_offset: int


def _section_for(
    sections: list[DetectedSection], page_number: int, offset: int
) -> str | None:
    """The most recent heading at or before this position in the document."""
    current: str | None = None
    for section in sections:
        if section.start_page > page_number:
            break
        if section.start_page < page_number:
            current = section.title
            continue
        # Same page: only counts if the heading appears at or before us.
        if section.start_offset is not None and section.start_offset <= offset:
            current = section.title
    return current


def _split_oversized(text: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """Break a paragraph that alone exceeds the chunk budget.

    Sentences first; only a single sentence longer than the budget is split by
    words, and that is a last resort rather than the normal path.
    """
    pieces: list[str] = []
    buffer = ""

    for sentence in _SENTENCE.split(text):
        if not sentence.strip():
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if counter.count(candidate) <= max_tokens:
            buffer = candidate
            continue

        if buffer:
            pieces.append(buffer)
            buffer = ""

        if counter.count(sentence) <= max_tokens:
            buffer = sentence
            continue

        # A single sentence over budget: split on words.
        words = sentence.split()
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if counter.count(trial) > max_tokens and current:
                pieces.append(current)
                current = word
            else:
                current = trial
        if current:
            buffer = current

    if buffer:
        pieces.append(buffer)
    return pieces


def _overlap_tail(text: str, counter: TokenCounter, overlap_tokens: int) -> str:
    """Trailing slice of `text` worth roughly `overlap_tokens` tokens.

    Taken at sentence granularity so the overlap is readable prose rather than
    a fragment starting mid-clause.
    """
    if overlap_tokens <= 0:
        return ""

    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    tail: list[str] = []
    for sentence in reversed(sentences):
        candidate = " ".join([sentence, *tail]).strip()
        if counter.count(candidate) > overlap_tokens and tail:
            break
        tail.insert(0, sentence)
    return " ".join(tail).strip()


def chunk_pages(
    pages: list[ParsedPage],
    sections: list[DetectedSection],
    counter: TokenCounter,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a document, respecting page, section, and paragraph boundaries.

    Chunks never span pages: a citation has to resolve to one page (PRD 5.2),
    and a chunk covering two pages could not.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    chunks: list[Chunk] = []

    for page in pages:
        text = page.cleaned_text
        if not text.strip():
            continue

        # Paragraph units, each with its offset into the page.
        units: list[tuple[str, int]] = []
        cursor = 0
        for para in _PARAGRAPH.split(text):
            if not para.strip():
                continue
            found = text.find(para, cursor)
            offset = found if found >= 0 else cursor
            cursor = offset + len(para)

            if counter.count(para) <= max_tokens:
                units.append((para, offset))
            else:
                inner = offset
                for piece in _split_oversized(para, counter, max_tokens):
                    found_piece = text.find(piece, inner)
                    piece_offset = found_piece if found_piece >= 0 else inner
                    inner = piece_offset + len(piece)
                    units.append((piece, piece_offset))

        buffer = ""
        buffer_start = 0

        def flush(end_offset: int) -> None:
            nonlocal buffer
            if not buffer.strip():
                return
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    content=buffer.strip(),
                    token_count=counter.count(buffer.strip()),
                    page_number=page.page_number,
                    section=_section_for(sections, page.page_number, buffer_start),
                    start_offset=buffer_start,
                    end_offset=end_offset,
                )
            )

        last_end = 0
        for para, offset in units:
            if not buffer:
                buffer = para
                buffer_start = offset
                last_end = offset + len(para)
                continue

            candidate = f"{buffer}\n\n{para}"
            if counter.count(candidate) <= max_tokens:
                buffer = candidate
                last_end = offset + len(para)
                continue

            flush(last_end)

            overlap = _overlap_tail(buffer, counter, overlap_tokens)
            if overlap and counter.count(f"{overlap}\n\n{para}") <= max_tokens:
                buffer = f"{overlap}\n\n{para}"
            else:
                buffer = para
            # Offsets always anchor to the real paragraph, never to the carried
            # overlap prefix, so start_offset stays a true position in the page.
            buffer_start = offset
            last_end = offset + len(para)

        flush(last_end)

    return chunks
