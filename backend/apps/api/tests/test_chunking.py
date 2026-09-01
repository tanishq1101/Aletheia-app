import pytest

from app.services.chunking import (
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    chunk_pages,
)
from app.services.providers import DetectedSection, ParsedPage


class WordCounter:
    """Deterministic stand-in for the model tokenizer.

    Chunker behaviour must be testable without loading a 120MB model; the real
    tokenizer is exercised separately in test_embedding.py.
    """

    def count(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def counter():
    return WordCounter()


def page(number: int, text: str) -> ParsedPage:
    return ParsedPage(page_number=number, raw_text=text, cleaned_text=text)


def test_short_page_becomes_one_chunk(counter):
    chunks = chunk_pages(
        [page(1, "one two three")], [], counter, max_tokens=50, overlap_tokens=5
    )

    assert len(chunks) == 1
    assert chunks[0].content == "one two three"
    assert chunks[0].token_count == 3
    assert chunks[0].page_number == 1


def test_chunks_never_exceed_the_token_budget(counter):
    body = "\n\n".join(" ".join(f"w{i}" for i in range(30)) for _ in range(10))

    chunks = chunk_pages([page(1, body)], [], counter, max_tokens=50, overlap_tokens=0)

    assert len(chunks) > 1
    assert all(c.token_count <= 50 for c in chunks)


def test_paragraph_boundaries_are_respected(counter):
    text = "alpha one two\n\nbravo three four\n\ncharlie five six"

    chunks = chunk_pages([page(1, text)], [], counter, max_tokens=6, overlap_tokens=0)

    # Each paragraph is 3 tokens; a 6-token budget fits two per chunk.
    assert len(chunks) == 2
    assert chunks[0].content == "alpha one two\n\nbravo three four"
    assert chunks[1].content == "charlie five six"


def test_chunks_never_span_pages(counter):
    """A citation must resolve to one page (PRD 5.2)."""
    pages = [page(1, "alpha one"), page(2, "bravo two"), page(3, "charlie three")]

    chunks = chunk_pages(pages, [], counter, max_tokens=500)

    assert [c.page_number for c in chunks] == [1, 2, 3]
    assert all(c.token_count == 2 for c in chunks)


def test_overlap_carries_context_between_chunks(counter):
    text = "\n\n".join(f"Sentence {i} here." for i in range(1, 9))

    with_overlap = chunk_pages(
        [page(1, text)], [], counter, max_tokens=9, overlap_tokens=3
    )
    without = chunk_pages([page(1, text)], [], counter, max_tokens=9, overlap_tokens=0)

    assert len(with_overlap) >= 2
    # Overlap re-includes trailing text, so it produces at least as many chunks
    # and the second chunk repeats content from the first.
    assert len(with_overlap) >= len(without)
    first_words = set(with_overlap[0].content.split())
    assert first_words & set(with_overlap[1].content.split())


def test_chunk_indexes_are_contiguous_across_pages(counter):
    pages = [page(n, "\n\n".join(f"para {i} of text" for i in range(4))) for n in (1, 2)]

    chunks = chunk_pages(pages, [], counter, max_tokens=8, overlap_tokens=0)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_sections_are_attributed_to_chunks(counter):
    text = "1 Introduction\n\nintro body here\n\n2 Methods\n\nmethod body here"
    sections = [
        DetectedSection("1 Introduction", 1, 0, 1, text.index("1 Introduction")),
        DetectedSection("2 Methods", 1, 1, 1, text.index("2 Methods")),
    ]

    chunks = chunk_pages(
        [page(1, text)], sections, counter, max_tokens=6, overlap_tokens=0
    )

    assert chunks[0].section == "1 Introduction"
    assert chunks[-1].section == "2 Methods"


def test_section_carries_over_to_later_pages(counter):
    pages = [page(1, "3 Methods\n\nbody"), page(2, "continued body text")]
    sections = [DetectedSection("3 Methods", 1, 0, 1, 0)]

    chunks = chunk_pages(pages, sections, counter, max_tokens=50, overlap_tokens=5)

    # Page 2 has no heading of its own, so it belongs to the last one seen.
    assert chunks[-1].page_number == 2
    assert chunks[-1].section == "3 Methods"


def test_offsets_point_into_the_page_text(counter):
    text = "alpha one two\n\nbravo three four\n\ncharlie five six"

    chunks = chunk_pages([page(1, text)], [], counter, max_tokens=6, overlap_tokens=0)

    for chunk in chunks:
        assert 0 <= chunk.start_offset <= len(text)
        assert chunk.end_offset <= len(text)
        assert chunk.start_offset < chunk.end_offset


def test_paragraph_larger_than_budget_is_split_on_sentences(counter):
    para = " ".join(f"This is sentence number {i}." for i in range(1, 21))

    chunks = chunk_pages([page(1, para)], [], counter, max_tokens=15, overlap_tokens=0)

    assert len(chunks) > 1
    assert all(c.token_count <= 15 for c in chunks)
    # Splitting happened at sentence ends, not mid-sentence.
    assert all(c.content.strip().endswith(".") for c in chunks)


def test_single_sentence_longer_than_budget_still_splits(counter):
    monster = " ".join(f"word{i}" for i in range(100))

    chunks = chunk_pages([page(1, monster)], [], counter, max_tokens=10, overlap_tokens=2)

    assert len(chunks) > 1
    assert all(c.token_count <= 10 for c in chunks)


def test_blank_pages_produce_no_chunks(counter):
    chunks = chunk_pages([page(1, "   \n\n  "), page(2, "real text")], [], counter)

    assert len(chunks) == 1
    assert chunks[0].page_number == 2


def test_invalid_parameters_are_rejected(counter):
    with pytest.raises(ValueError):
        chunk_pages([page(1, "x")], [], counter, max_tokens=0)
    with pytest.raises(ValueError):
        chunk_pages([page(1, "x")], [], counter, max_tokens=10, overlap_tokens=10)


@pytest.mark.parametrize("size", [400, 600, 800])
def test_prd_benchmark_sizes_are_all_supported(counter, size):
    """PRD 3.2 benchmarks 400/600/800 tokens — all three must be usable."""
    body = "\n\n".join(" ".join(f"w{i}" for i in range(50)) for _ in range(40))

    chunks = chunk_pages([page(1, body)], [], counter, max_tokens=size)

    assert chunks
    assert all(c.token_count <= size for c in chunks)


def test_defaults_are_sane():
    assert DEFAULT_OVERLAP_TOKENS < DEFAULT_CHUNK_TOKENS
