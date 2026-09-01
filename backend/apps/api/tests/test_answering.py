"""Grounded answering tests (PRD 5.3, 5.4, Section 12).

Retrieval, reranking, and citation resolution run for real against the real
models and a real database. **The LLM is scripted**, and deliberately so: the
properties under test are "does the backend refuse to pass through a citation it
never issued" and "does an evidence ID resolve to the right page" — both are the
backend's job, and both must hold no matter which model is configured or how
badly it misbehaves. A live model could not be made to fabricate a citation on
demand, so it could not test the guard rail at all.

The live OpenRouter check lives in `test_llm_openrouter.py`.
"""

from uuid import uuid4

import pytest

from app.api.answer import get_llm_provider
from app.services.answering import (
    extract_cited_ids,
    strip_fabricated_citations,
)
from main import app
from tests.fixtures import build_pdf

TOPIC_PAGES = [
    [
        "1 Optimization",
        "",
        "Residual connections let gradients flow through very deep networks and",
        "make optimization of hundreds of layers tractable in practice.",
    ],
    [
        "2 Tokenization",
        "",
        "Subword tokenization splits rare words into smaller units so the model",
        "vocabulary stays bounded while still covering unseen terms.",
    ],
    [
        "3 Evaluation",
        "",
        "We report precision and recall on a held-out benchmark and compare",
        "against previously published baselines under identical conditions.",
    ],
]


class ScriptedLLM:
    """An LLMProvider that returns a fixed reply and records what it was sent."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.system: str | None = None
        self.prompt: str | None = None
        self.calls = 0

    name = "scripted-test-model"

    def complete(self, *, system: str, prompt: str) -> str:
        self.calls += 1
        self.system, self.prompt = system, prompt
        return self.reply


class BrokenLLM:
    name = "broken-test-model"

    def complete(self, *, system: str, prompt: str) -> str:
        from app.services.llm import LLMError

        raise LLMError("upstream returned 502: provider unavailable")


@pytest.fixture
def corpus(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={
            "file": (
                "topics.pdf",
                build_pdf(TOPIC_PAGES, title="Topics", author="Tester"),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    paper = client.get(f"/papers/{response.json()['id']}").json()
    assert paper["status"] == "ready", paper["job"]
    return {"project_id": project["id"], "paper_id": paper["id"]}


@pytest.fixture
def scripted():
    """Install a scripted LLM for the duration of one test."""
    holder: dict = {}

    def use(reply: str) -> ScriptedLLM:
        llm = ScriptedLLM(reply)
        holder["llm"] = llm
        app.dependency_overrides[get_llm_provider] = lambda: llm
        return llm

    yield use
    app.dependency_overrides.pop(get_llm_provider, None)


def ask(client, project_id, query="how do gradients flow in deep networks?", **kwargs):
    return client.post(
        f"/projects/{project_id}/answer", json={"query": query, **kwargs}
    )


# === Citation parsing and validation (no database, no model) ================


def test_extract_cited_ids_reads_bracketed_ids_only():
    answer = "Depth helps [E1]. Later work E3 disagreed, see [E2, E4]."

    # "E3" outside brackets is the paper's own prose, not a citation.
    assert extract_cited_ids(answer) == ["E1", "E2", "E4"]


def test_extract_cited_ids_deduplicates_in_order_of_first_mention():
    assert extract_cited_ids("[E2] then [E1] then [E2]") == ["E2", "E1"]


def test_fabricated_ids_are_stripped():
    """PRD 5.3: the model may only cite an ID it was actually handed."""
    answer = "Depth helps [E1]. Batch size was 256 [E9]."

    cleaned, removed = strip_fabricated_citations(answer, {"E1", "E2"})

    assert removed == 1
    assert "E9" not in cleaned
    assert "[E1]" in cleaned
    # The claim itself stays, now visibly uncited rather than falsely supported.
    assert "Batch size was 256" in cleaned


def test_a_mixed_citation_keeps_only_the_real_ids():
    cleaned, removed = strip_fabricated_citations("Depth helps [E1, E7].", {"E1"})

    assert removed == 1
    assert cleaned == "Depth helps [E1]."


def test_stripping_the_only_citation_leaves_no_empty_brackets():
    cleaned, removed = strip_fabricated_citations("Depth helps [E9].", {"E1"})

    assert removed == 1
    assert "[" not in cleaned and "]" not in cleaned
    assert cleaned == "Depth helps."


def test_valid_citations_are_left_untouched():
    answer = "Depth helps [E1] and width helps [E2, E3]."

    cleaned, removed = strip_fabricated_citations(answer, {"E1", "E2", "E3"})

    assert removed == 0
    assert cleaned == answer


# === End to end through the API =============================================


def test_answer_is_grounded_and_citations_resolve(client, corpus, scripted):
    """An evidence ID must resolve to the real page it came from (PRD 5.2)."""
    scripted("Residual connections let gradients flow through deep networks [E1].")

    body = ask(client, corpus["project_id"]).json()

    assert body["sufficient_evidence"] is True
    assert body["fabricated_citations_removed"] == 0
    assert len(body["citations"]) == 1

    citation = body["citations"][0]
    assert citation["evidence_id"] == "E1"
    # The optimization content is on page 1 of the corpus.
    assert citation["page_number"] == 1
    assert citation["paper_id"] == corpus["paper_id"]
    assert "Residual connections" in citation["snippet"]
    assert citation["location"].endswith("page 1")


def test_reranking_puts_the_relevant_passage_first(client, corpus, scripted):
    """E1 is the top-ranked evidence, so it must be the on-topic page."""
    scripted("Answer [E1].")

    body = ask(client, corpus["project_id"], "splitting rare words into subwords").json()

    assert body["evidence"][0]["page_number"] == 2
    assert "Subword tokenization" in body["evidence"][0]["content"]


def test_evidence_is_narrowed_below_the_candidate_set(client, corpus, scripted):
    """PRD 5.1 step 7: ~20 candidates in, 5-8 evidence blocks out."""
    scripted("Answer [E1].")

    body = ask(client, corpus["project_id"], top_k=20, rerank_top_k=2).json()

    assert len(body["evidence"]) == 2
    assert body["candidates_considered"] >= len(body["evidence"])


def test_fabricated_citation_never_reaches_the_response(client, corpus, scripted):
    """The single most important test in this sprint.

    A model that invents [E99] must not produce a citation the UI would render
    as authoritative. PRD Section 12 requires zero fabricated citation IDs.
    """
    scripted("Depth helps [E1]. The learning rate was 0.1 [E99].")

    body = ask(client, corpus["project_id"]).json()

    assert body["fabricated_citations_removed"] == 1
    assert "E99" not in body["answer"]
    assert [c["evidence_id"] for c in body["citations"]] == ["E1"]


def test_insufficient_evidence_is_reported_not_guessed(client, corpus, scripted):
    """PRD 5.4: say so explicitly rather than answering from model knowledge."""
    scripted("INSUFFICIENT_EVIDENCE\nThe papers do not report training hardware.")

    body = ask(client, corpus["project_id"], "what GPUs were used for training?").json()

    assert body["sufficient_evidence"] is False
    assert "INSUFFICIENT_EVIDENCE" not in body["answer"]
    assert "do not report training hardware" in body["answer"]
    assert body["citations"] == []


def test_the_model_is_given_evidence_ids_not_chunk_ids(client, corpus, scripted):
    """PRD 5.3: IDs are minted backend-side; the model never sees a chunk id."""
    llm = scripted("Answer [E1].")

    body = ask(client, corpus["project_id"]).json()

    assert '<EVIDENCE id="E1"' in llm.prompt
    for evidence in body["evidence"]:
        assert evidence["chunk_id"] not in llm.prompt
    # And the grounding rules actually reached the model.
    assert "ONLY the evidence blocks" in llm.system
    assert "INSUFFICIENT_EVIDENCE" in llm.system


def test_evidence_carries_both_scores_separately(client, corpus, scripted):
    """Cosine similarity and cross-encoder logits are different quantities."""
    scripted("Answer [E1].")

    evidence = ask(client, corpus["project_id"]).json()["evidence"][0]

    assert -1.0 <= evidence["similarity"] <= 1.0
    assert "rerank_score" in evidence
    assert evidence["rerank_score"] != evidence["similarity"]


def test_empty_project_does_not_spend_an_llm_call(client, project, scripted):
    llm = scripted("this should never be returned")

    body = ask(client, project["id"]).json()

    assert llm.calls == 0
    assert body["sufficient_evidence"] is False
    assert body["citations"] == []
    assert body["candidates_considered"] == 0


def test_llm_failure_surfaces_a_real_reason(client, corpus):
    """PRD Section 9: never silently swallow a provider failure."""
    app.dependency_overrides[get_llm_provider] = lambda: BrokenLLM()
    try:
        response = ask(client, corpus["project_id"])
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    assert response.status_code == 503
    assert "502" in response.json()["detail"]
    assert "provider unavailable" in response.json()["detail"]


def test_answer_on_unknown_project_is_404(client, scripted):
    scripted("Answer [E1].")
    assert ask(client, uuid4()).status_code == 404


def test_empty_question_is_rejected(client, project, scripted):
    scripted("Answer [E1].")
    assert ask(client, project["id"], query="").status_code == 422
