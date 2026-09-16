"""Report export: what a PDF contains, and what it must never claim.

The document model is tested without a PDF engine; the renderer is tested by
extracting the text back out of real PDF bytes, because "it returned bytes" is
not evidence that a reader can read it.
"""

import re

import pymupdf
import pytest

from app.schemas.models import (
    AgentResearchResponse,
    AgentStepResponse,
    AnswerResponse,
    CitationOut,
    ReproducibilityCheck,
    ReproducibilityReport,
)
from app.services.pdf import render_pdf
from app.services.report import (
    agent_document,
    answer_document,
    reproducibility_document,
)


def citation(evidence_id="E1", title="Attention Is All You Need", snippet="BLEU of 41.8."):
    return CitationOut(
        evidence_id=evidence_id,
        chunk_id="33333333-3333-3333-3333-333333333333",
        paper_id="44444444-4444-4444-4444-444444444444",
        paper_title=title,
        page_number=5, section="Results", location="Section Results, page 5",
        snippet=snippet,
    )


def answer(**overrides):
    payload = {
        "answer": "The model reports **41.8 BLEU** [E1].",
        "sufficient_evidence": True,
        "citations": [citation()],
        "evidence": [],
        "fabricated_citations_removed": 0,
        "candidates_considered": 20,
        "evidence_dropped_for_budget": 0,
        "model": "gpt-5.6-luna",
    }
    payload.update(overrides)
    return AnswerResponse(**payload)


def run(**overrides):
    payload = {
        "goal": "How well does the model translate?",
        "planned_questions": ["What BLEU is reported?"],
        "planner_fallback_used": False,
        "steps": [AgentStepResponse(question="What BLEU is reported?",
                                    status="succeeded", answer=answer())],
        "model": "gpt-5.6-luna",
        "synthesis": answer(),
    }
    payload.update(overrides)
    return AgentResearchResponse(**payload)


def text_of(document) -> str:
    """The rendered PDF's text, with layout whitespace collapsed.

    A sentence that wraps across two lines is still that sentence to a reader,
    so these tests assert on content and leave line breaking to the renderer.
    """
    with pymupdf.open(stream=render_pdf(document), filetype="pdf") as opened:
        return re.sub(r"\s+", " ", " ".join(page.get_text() for page in opened))


# --- What the reader must be told -------------------------------------------

def test_a_non_reproducible_answer_says_so_on_the_report():
    """The models this ships against refuse temperature=0. A PDF is read away
    from the app and outlives the session, so it cannot rely on the screen to
    carry the caveat."""
    body = text_of(answer_document(question="q", answer=answer(reproducible=False)))
    assert "not reproducible" in body
    assert "Cited passages remain exact" in body


def test_a_reproducible_answer_makes_no_such_claim():
    assert "not reproducible" not in text_of(
        answer_document(question="q", answer=answer(reproducible=True))
    )


def test_insufficient_evidence_is_reported_as_an_outcome_not_a_failure():
    body = text_of(answer_document(question="q", answer=answer(
        sufficient_evidence=False, answer="INSUFFICIENT_EVIDENCE")))
    assert "insufficient" in body.lower()
    assert "coverage" in body.lower()


def test_removed_fabricated_citations_are_disclosed():
    body = text_of(answer_document(
        question="q", answer=answer(fabricated_citations_removed=2)))
    assert "2 citation ID(s) the model invented were removed" in body


# --- Evidence travels with the report ---------------------------------------

def test_every_cited_passage_is_reproduced_in_the_pdf():
    """A claim whose passage stayed in the browser is a claim the reader of the
    PDF cannot check, which is the one thing this application exists to stop."""
    body = text_of(answer_document(question="q", answer=answer(
        citations=[citation("E1", "Attention Is All You Need", "We report 41.8 BLEU."),
                   citation("E2", "BERT", "Pre-training improves GLUE.")])))
    assert "We report 41.8 BLEU." in body
    assert "Pre-training improves GLUE." in body
    assert "Attention Is All You Need" in body and "BERT" in body


def test_a_long_passage_is_elided_rather_than_dropped():
    body = text_of(answer_document(question="q", answer=answer(
        citations=[citation(snippet="word " * 400)])))
    assert "…" in body, "truncation is visible, not silent"


# --- Markdown the answering prompt actually asks the model for ---------------

def test_markdown_emphasis_does_not_reach_the_reader_as_asterisks():
    body = text_of(answer_document(question="q", answer=answer(
        answer="The result is **41.8 BLEU** and *approximate*.")))
    assert "41.8 BLEU" in body and "**" not in body


def test_the_comparison_table_renders_as_a_table_not_pipes():
    body = text_of(answer_document(question="q", answer=answer(answer=(
        "Findings:\n\n"
        "| Method | Metric | Value | Unit | Dataset | Conditions | Evidence |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| RAG-Sequence | EM | 44.5 | score | NQ | 50 docs | [E1] |\n"
    ))))
    assert "RAG-Sequence" in body and "44.5" in body
    assert "| --- |" not in body and "| RAG-Sequence |" not in body


def test_headings_and_lists_survive():
    body = text_of(answer_document(question="q", answer=answer(answer=(
        "# Direct answer\n\nText.\n\n- first point\n- second point\n"))))
    assert "Direct answer" in body
    assert "first point" in body and "second point" in body
    assert "# Direct" not in body and "- first" not in body


def test_source_text_cannot_inject_markup_into_the_pdf():
    """Evidence is data. A passage containing angle brackets must not be read
    as the renderer's own markup."""
    body = text_of(answer_document(question="q", answer=answer(
        citations=[citation(snippet="Values where a <b> b & c </b> hold.")])))
    assert "<b>" in body, "shown literally, not interpreted"


# --- The research brief ------------------------------------------------------

def test_a_brief_records_how_it_was_built():
    body = text_of(agent_document(run=run()))
    assert "Research Brief" in body
    assert "What the evidence says" in body
    assert "How this brief was built" in body
    assert "What BLEU is reported?" in body


def test_a_brief_without_a_combined_report_says_that_plainly():
    """The failure has to be stated, not implied by an empty section."""
    document = agent_document(run=run(
        synthesis=None,
        synthesis_error="The combined report could not be generated. Reason: boom",
    ))
    body = text_of(document)
    assert "No combined report was produced" in body
    assert "boom" in body, "the real reason travels with the report"


def test_a_failed_question_is_shown_as_failed_not_omitted():
    body = text_of(agent_document(run=run(steps=[AgentStepResponse(
        question="Unanswerable?", status="failed", error="provider exploded")])))
    assert "Unanswerable?" in body
    assert "not answered" in body and "provider exploded" in body


def test_a_planner_fallback_is_disclosed():
    assert "answers the original goal directly" in text_of(
        agent_document(run=run(planner_fallback_used=True)))


def test_public_sources_are_labelled_as_leads_not_evidence():
    body = text_of(agent_document(run=run(discoveries=[{
        "title": "Some preprint", "provider": "Europe PMC", "year": 2026,
        "evidence_scope": "abstract only", "url": "https://example.test/a"}])))
    assert "not automatically trusted evidence" in body
    assert "Some preprint" in body


# --- Reproducibility ---------------------------------------------------------

def _report(**overrides):
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "paper_id": "22222222-2222-2222-2222-222222222222",
        "score": 0.62, "repo_metadata": {"stars": 12}, "links": [],
        "model": "gpt-5.6-luna", "created_at": "2026-09-15T00:00:00Z",
        "checks": [ReproducibilityCheck(dimension="Code availability",
                                        status="partially_disclosed",
                                        rationale="A repository is named [E1].",
                                        citations=[citation()], check_index=0)],
    }
    payload.update(overrides)
    return ReproducibilityReport(**payload)


def test_a_disclosure_audit_does_not_claim_the_results_reproduce():
    body = text_of(reproducibility_document(report=_report(), paper_title="Attention"))
    assert "discloses" in body
    assert "Nothing here executed the paper's code." in body
    assert "62%" in body and "Code availability" in body


# --- Filenames ---------------------------------------------------------------

def test_the_filename_names_the_question_it_answers():
    document = agent_document(run=run(goal="Does RAG beat fine-tuning?"))
    assert document.filename.startswith("aletheia-brief-does-rag-beat-fine-tuning-")
    assert document.filename.endswith(".pdf")


@pytest.mark.parametrize("goal", ["", "///", "a" * 500, "naïve — ünïcode ✓"])
def test_an_awkward_goal_still_produces_a_usable_filename(goal):
    name = agent_document(run=run(goal=goal or "x")).filename
    assert name.endswith(".pdf")
    assert all(c.isalnum() or c in "-." for c in name), name


def test_latex_delimiters_do_not_reach_the_reader():
    """The prompt asks for plain-text maths; a model that reaches for LaTeX
    anyway must not put `\\(O(n^2)\\)` in front of a reader, since nothing in
    this application renders it."""
    body = text_of(answer_document(question="q", answer=answer(
        answer=r"Attention costs \(O(n^2 d)\) per layer, and \[O(1)\] steps.")))
    assert "O(n^2 d)" in body and "O(1)" in body
    assert "\\(" not in body and "\\[" not in body
