"""Model-written "what to ask next" (services/follow_ups.py).

The model is scripted throughout, and for the same reason it is scripted in
test_answering.py: the properties worth testing belong to the backend, not the
provider. They are "does a reply that does not meet the stated contract get
discarded rather than shown", and — the important one — "can anything that
happens here lose an answer that was already produced and validated". Neither
could be tested against a live model, which cannot be made to return a
malformed suggestion or a 502 on demand.
"""

import json
import os

import pytest

from app.api.answer import get_llm_provider
from app.core.config import get_settings
from app.services.answering import answer_from_context
from app.services.context import BuiltContext, Evidence
from app.services.follow_ups import MAX_QUESTION_CHARS, suggest_follow_ups
from app.services.llm import LLMError
from main import app
from tests.fixtures import build_pdf

PAGES = [
    [
        "1 Retrieval",
        "",
        "Dense retrieval encodes the query and passage into one vector each and",
        "ranks by inner product over the whole collection.",
    ],
    [
        "2 Reranking",
        "",
        "A cross-encoder scores the query and passage jointly and is far more",
        "accurate than a bi-encoder at a much higher cost per pair.",
    ],
]


def make_evidence(count: int = 2) -> list[Evidence]:
    return [
        Evidence(
            evidence_id=f"E{index + 1}",
            chunk_id=f"chunk-{index}",
            paper_id="paper-1",
            paper_title="A Retrieval Paper",
            content=f"Passage {index} about retrieval and reranking.",
            section="Method",
            page_number=index + 1,
            similarity=0.5,
            rerank_score=1.0,
        )
        for index in range(count)
    ]


class Replies:
    """A provider that returns a scripted reply per call, in order."""

    name = "scripted-test-model"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, system: str, prompt: str, max_output_tokens=None) -> str:
        self.prompts.append((system, prompt))
        if not self.replies:
            raise AssertionError("the provider was called more times than scripted")
        return self.replies.pop(0)


def questions(*values: str) -> str:
    return json.dumps({"questions": list(values)})


def ask_for(llm, *, question="what is dense retrieval?", answer="Dense retrieval encodes text [E1].", evidence=None):
    return suggest_follow_ups(
        question=question,
        answer=answer,
        evidence=make_evidence() if evidence is None else evidence,
        cited_ids={"E1"},
        llm=llm,
    )


# === The contract the prompt asks for is enforced here, not assumed =========


def test_returns_the_questions_the_model_proposed():
    llm = Replies(questions(
        "How does the cross-encoder's cost scale with the candidate set?",
        "Which datasets were used to compare the two rankers?",
    ))

    assert ask_for(llm) == [
        "How does the cross-encoder's cost scale with the candidate set?",
        "Which datasets were used to compare the two rankers?",
    ]


def test_a_fenced_reply_is_still_read():
    """Providers wrap JSON in a code fence however plainly they are told not to."""
    llm = Replies(f"```json\n{questions('What did the reranker cost per pair?')}\n```")

    assert ask_for(llm) == ["What did the reranker cost per pair?"]


def test_statements_are_dropped_because_they_are_not_questions():
    llm = Replies(questions(
        "The reranker is more accurate.",
        "What did the reranker cost per pair?",
    ))

    assert ask_for(llm) == ["What did the reranker cost per pair?"]


def test_an_overlong_question_is_dropped_rather_than_truncated():
    """Half a question is worse than none — it cannot be accepted with Tab."""
    long_question = "Why " + ("very " * 100) + "slow?"
    assert len(long_question) > MAX_QUESTION_CHARS
    llm = Replies(questions(long_question, "What is the cost per pair?"))

    assert ask_for(llm) == ["What is the cost per pair?"]


def test_the_question_just_asked_is_not_offered_back():
    llm = Replies(questions(
        "  What is   DENSE retrieval  ",  # same question, different shape
        "What is the cost per pair?",
    ))

    assert ask_for(llm, question="What is dense retrieval?") == [
        "What is the cost per pair?"
    ]


def test_duplicates_are_collapsed():
    llm = Replies(questions(
        "What is the cost per pair?",
        "what is the cost per pair?",
    ))

    assert ask_for(llm) == ["What is the cost per pair?"]


def test_more_questions_than_requested_are_cut_to_the_limit():
    llm = Replies(questions(*[f"Question number {n}?" for n in range(10)]))

    result = suggest_follow_ups(
        question="q", answer="a [E1].", evidence=make_evidence(),
        cited_ids={"E1"}, llm=llm, limit=2,
    )

    assert result == ["Question number 0?", "Question number 1?"]


# === Nothing here may cost an answer =======================================


def test_a_provider_failure_yields_no_suggestions_rather_than_an_error():
    class Broken:
        name = "broken"

        def complete(self, **_):
            raise LLMError("upstream returned 502: provider unavailable")

    assert ask_for(Broken()) == []


def test_an_unparseable_reply_yields_no_suggestions():
    assert ask_for(Replies("I'd suggest asking about the reranker next!")) == []


def test_a_reply_of_the_wrong_shape_yields_no_suggestions():
    assert ask_for(Replies(json.dumps({"questions": "not a list"}))) == []


def test_an_unexpected_failure_still_yields_no_suggestions():
    """The broad guard in the service, exercised rather than assumed.

    A bug in this module must not be able to throw away a validated answer, so
    there is an `except Exception` there. A test that never runs it is not
    evidence that it works.
    """

    class Exploding:
        name = "exploding"

        def complete(self, **_):
            raise ZeroDivisionError("something nobody anticipated")

    assert ask_for(Exploding()) == []


# === Calls that are not worth making are not made ==========================


def test_no_model_call_when_there_was_no_evidence():
    llm = Replies()  # any call raises

    assert ask_for(llm, evidence=[]) == []
    assert llm.prompts == []


def test_no_model_call_when_the_feature_is_switched_off():
    llm = Replies()
    previous = os.environ.get("FOLLOW_UP_SUGGESTIONS_ENABLED")
    os.environ["FOLLOW_UP_SUGGESTIONS_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        assert ask_for(llm) == []
        assert llm.prompts == []
    finally:
        if previous is None:
            os.environ.pop("FOLLOW_UP_SUGGESTIONS_ENABLED", None)
        else:
            os.environ["FOLLOW_UP_SUGGESTIONS_ENABLED"] = previous
        get_settings.cache_clear()


def test_the_suggester_is_shown_which_evidence_went_uncited():
    """The uncited blocks are the point: retrieved, relevant, unaccounted for."""
    llm = Replies(questions("What does the second passage add?"))

    suggest_follow_ups(
        question="q", answer="a [E1].", evidence=make_evidence(2),
        cited_ids={"E1"}, llm=llm,
    )

    _, prompt = llm.prompts[0]
    assert "[E1] (cited)" in prompt
    assert "[E2] (NOT cited)" in prompt


# === Integration with the answering pipeline ===============================


def build_context_for(evidence: list[Evidence]) -> BuiltContext:
    return BuiltContext(
        evidence=evidence,
        text="\n".join(f"<EVIDENCE id={e.evidence_id}>{e.content}" for e in evidence),
        dropped_for_budget=0,
        token_count=64,
    )


def test_answering_does_not_suggest_unless_asked():
    """Off by default: the research agent runs this once per planned question."""
    llm = Replies("Dense retrieval encodes text [E1].")

    result = answer_from_context(
        question="what is dense retrieval?",
        context=build_context_for(make_evidence()),
        llm=llm,
        candidates_considered=2,
    )

    assert result.follow_ups == []
    assert len(llm.prompts) == 1, "a second call was made without being asked for"


def test_the_suggester_sees_the_answer_as_the_reader_will():
    """A stripped fabricated citation must not reappear in the second prompt."""
    llm = Replies(
        "Dense retrieval encodes text [E1]. Batch size was 256 [E9].",
        questions("What batch size did the paper report?"),
    )

    result = answer_from_context(
        question="what is dense retrieval?",
        context=build_context_for(make_evidence()),
        llm=llm,
        candidates_considered=2,
        suggest_next=True,
    )

    assert result.fabricated_citations_removed == 1
    _, follow_up_prompt = llm.prompts[1]
    assert "E9" not in follow_up_prompt
    assert result.follow_ups == ["What batch size did the paper report?"]


# === Through the API =======================================================


@pytest.fixture
def corpus(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("retrieval.pdf", build_pdf(PAGES, title="Retrieval"), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    paper = client.get(f"/papers/{response.json()['id']}").json()
    assert paper["status"] == "ready", paper["job"]
    return project["id"]


@pytest.fixture
def two_replies():
    holder: dict = {}

    def use(*replies: str) -> Replies:
        llm = Replies(*replies)
        holder["llm"] = llm
        app.dependency_overrides[get_llm_provider] = lambda: llm
        return llm

    yield use
    app.dependency_overrides.pop(get_llm_provider, None)


def test_the_answer_endpoint_returns_follow_ups(client, corpus, two_replies):
    two_replies(
        "A cross-encoder scores the pair jointly [E1].",
        questions("How much does the cross-encoder cost per pair?"),
    )

    body = client.post(
        f"/projects/{corpus}/answer", json={"query": "how does reranking work?"}
    ).json()

    assert body["follow_ups"] == ["How much does the cross-encoder cost per pair?"]


def test_an_answer_survives_a_failed_suggestion(client, corpus, two_replies):
    """The whole point of the separate call, asserted end to end."""
    two_replies(
        "A cross-encoder scores the pair jointly [E1].",
        "not json, not questions, not anything",
    )

    response = client.post(
        f"/projects/{corpus}/answer", json={"query": "how does reranking work?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citations"], "the answer lost its citations"
    assert body["follow_ups"] == []


def test_a_conversation_stores_its_follow_ups(client, corpus, two_replies):
    """Reopening a thread offers the questions it offered when it was answered."""
    two_replies(
        "A cross-encoder scores the pair jointly [E1].",
        questions("Which datasets was the reranker evaluated on?"),
    )
    conversation = client.post(
        f"/projects/{corpus}/conversations", json={}
    ).json()

    exchange = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"query": "how does reranking work?"},
    ).json()
    assert exchange["assistant_message"]["metadata"]["follow_ups"] == [
        "Which datasets was the reranker evaluated on?"
    ]

    # And again from storage, with no further model call.
    reloaded = client.get(f"/conversations/{conversation['id']}/messages").json()
    assistant = [m for m in reloaded if m["role"] == "assistant"][0]
    assert assistant["metadata"]["follow_ups"] == [
        "Which datasets was the reranker evaluated on?"
    ]
