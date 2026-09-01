"""Context builder tests — evidence IDs and the citation resolution path.

No model and no database here: this is pure assembly logic, and it is the
layer PRD Section 5.3 depends on most.
"""

from uuid import uuid4

from app.services.answering import extract_cited_ids
from app.services.context import Evidence, assign_evidence_ids, build_context
from app.services.retrieval import RetrievedChunk


class WordCounter:
    """Deterministic stand-in for the model tokenizer (as in test_chunking)."""

    def count(self, text: str) -> int:
        return len(text.split())


def chunk(content="some content", section="3.1 Training", page=7, similarity=0.9):
    return RetrievedChunk(
        chunk_id=uuid4(),
        paper_id=uuid4(),
        paper_title="A Paper",
        filename="paper.pdf",
        content=content,
        section=section,
        chunk_index=0,
        token_count=len(content.split()),
        page_number=page,
        similarity=similarity,
    )


def build(chunks_and_scores, max_tokens=1000):
    return build_context(
        ranked=assign_evidence_ids(chunks_and_scores),
        counter=WordCounter(),
        max_tokens=max_tokens,
    )


def test_evidence_ids_are_assigned_in_rank_order():
    """E1 is the best-ranked block. The model is never given a chunk id."""
    ranked = [(chunk(content="best"), 5.0), (chunk(content="second"), 1.0)]

    context = build(ranked)

    assert [item.evidence_id for item in context.evidence] == ["E1", "E2"]
    assert context.evidence[0].content == "best"
    # The chunk's real UUID must not leak into the prompt.
    assert str(ranked[0][0].chunk_id) not in context.text


def test_blocks_carry_page_and_section():
    context = build([(chunk(section="3.2 Results", page=7), 2.0)])

    assert '<EVIDENCE id="E1"' in context.text
    assert 'page="7"' in context.text
    assert 'section="3.2 Results"' in context.text
    assert "</EVIDENCE>" in context.text


def test_missing_section_degrades_to_page_only():
    """A chunk before the first heading has no section (PROGRESS.md handoff).

    It must never render as the string "null" or "None" — to the model that
    looks like a citable section name.
    """
    context = build([(chunk(section=None, page=4), 2.0)])

    assert "section=" not in context.text
    assert "None" not in context.text
    assert "null" not in context.text
    assert context.evidence[0].location == "page 4"


def test_location_prefers_section_and_page_together():
    context = build([(chunk(section="3.2 Results", page=7), 2.0)])
    assert context.evidence[0].location == "Section 3.2 Results, page 7"


def test_location_survives_a_missing_page():
    context = build([(chunk(section=None, page=None), 2.0)])
    assert context.evidence[0].location == "location unavailable"


def test_quotes_in_a_title_cannot_break_the_block():
    """An unescaped quote would end the attribute list early and corrupt every
    following attribute — including the id the model is told to cite."""
    item = chunk()
    item = RetrievedChunk(**{**vars(item), "paper_title": 'The "Best" Paper'})

    context = build([(item, 2.0)])

    assert '<EVIDENCE id="E1" paper="The \'Best\' Paper"' in context.text
    assert 'page="7"' in context.text


def test_budget_drops_lowest_ranked_evidence_and_reports_it():
    """Silently truncating evidence produces an answer indistinguishable from a
    well-grounded one. The count has to come back."""
    ranked = [(chunk(content=" ".join(["word"] * 30)), float(10 - i)) for i in range(5)]

    context = build(ranked, max_tokens=80)

    assert len(context.evidence) < 5
    assert context.dropped_for_budget == 5 - len(context.evidence)
    # What survives is the best-ranked prefix, not an arbitrary subset.
    assert [i.evidence_id for i in context.evidence] == [
        f"E{n}" for n in range(1, len(context.evidence) + 1)
    ]


def test_a_single_oversized_block_is_still_supplied():
    """Returning no evidence at all would be worse than one over-budget block."""
    context = build([(chunk(content=" ".join(["word"] * 500)), 1.0)], max_tokens=10)

    assert len(context.evidence) == 1
    assert context.dropped_for_budget == 0


def test_empty_ranking_produces_empty_context():
    context = build([])

    assert context.evidence == []
    assert context.text == ""
    assert context.evidence_ids == set()


def test_assigned_ids_are_the_ids_the_parser_will_look_for():
    """The IDs written into the prompt must be the ones citation parsing reads
    back out, or a correctly cited answer would resolve to nothing."""
    context = build([(chunk(), 1.0), (chunk(), 0.5)])

    assert extract_cited_ids("Claim [E1] and claim [E2].") == ["E1", "E2"]
    assert context.evidence_ids == {"E1", "E2"}


def test_evidence_exposes_ids_as_a_set_for_validation():
    context = build([(chunk(), 1.0), (chunk(), 0.5)])
    assert context.evidence_ids == {"E1", "E2"}
    assert isinstance(context.evidence[0], Evidence)
