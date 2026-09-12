"""Conversation persistence (PRD Sprint 5).

Answering itself is covered by test_answering.py. What matters here is that an
exchange survives the request: both turns stored, citations attached to the
assistant turn, and the evidence still resolvable when the conversation is read
back later. The LLM is scripted for the same reason as in test_answering.py —
the property under test is the backend's, not the model's.
"""

from uuid import uuid4

import pytest

from app.api.answer import get_llm_provider
from main import app
from tests.fixtures import build_pdf
from tests.test_answering import TOPIC_PAGES, BrokenLLM, ScriptedLLM


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
    def use(reply: str) -> ScriptedLLM:
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm_provider] = lambda: llm
        return llm

    yield use
    app.dependency_overrides.pop(get_llm_provider, None)


def open_conversation(client, project_id, **payload):
    response = client.post(f"/projects/{project_id}/conversations", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_conversation_is_created_and_listed(client, project):
    conversation = open_conversation(client, project["id"])

    assert conversation["project_id"] == project["id"]
    assert conversation["message_count"] == 0

    listed = client.get(f"/projects/{project['id']}/conversations").json()
    assert [c["id"] for c in listed] == [conversation["id"]]


def test_conversation_requires_a_real_project(client):
    response = client.post(f"/projects/{uuid4()}/conversations", json={})
    assert response.status_code == 404


def test_exchange_is_persisted_with_citations(client, corpus, scripted):
    scripted("Residual connections help gradients flow [E1].")
    conversation = open_conversation(client, corpus["project_id"])

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"query": "how do gradients flow in deep networks?"},
    )
    assert response.status_code == 201, response.text
    exchange = response.json()

    assert exchange["user_message"]["role"] == "user"
    assert exchange["assistant_message"]["role"] == "assistant"
    assert exchange["assistant_message"]["metadata"]["sufficient_evidence"] is True
    assert exchange["assistant_message"]["citations"], "the answer cited evidence"

    # Read back: the stored exchange must carry the same citations, resolved.
    messages = client.get(f"/conversations/{conversation['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]

    stored = messages[1]["citations"]
    assert len(stored) == len(exchange["assistant_message"]["citations"])
    assert stored[0]["evidence_id"].startswith("E")
    assert stored[0]["paper_id"] == corpus["paper_id"]
    # A citation is only useful if it still points at a real location.
    assert stored[0]["location"]
    assert stored[0]["snippet"]


def test_fabricated_citations_are_never_stored(client, corpus, scripted):
    """PRD Section 12 applies to persisted answers too, not just responses."""
    scripted("Depth helps [E1]. Batch size was 256 [E99].")
    conversation = open_conversation(client, corpus["project_id"])

    client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"query": "how do gradients flow in deep networks?"},
    )

    messages = client.get(f"/conversations/{conversation['id']}/messages").json()
    assistant = messages[1]
    assert "E99" not in assistant["content"]
    assert all(c["evidence_id"] != "E99" for c in assistant["citations"])
    assert assistant["metadata"]["fabricated_citations_removed"] == 1


def test_insufficient_evidence_is_stored_as_an_answer(client, corpus, scripted):
    """PRD 5.4: refusing to answer is a real outcome, not a failed request."""
    scripted("INSUFFICIENT_EVIDENCE\nThe paper does not report training cost.")
    conversation = open_conversation(client, corpus["project_id"])

    response = client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"query": "what did the model cost to train?"},
    )
    assert response.status_code == 201

    assistant = response.json()["assistant_message"]
    assert assistant["metadata"]["sufficient_evidence"] is False
    assert "INSUFFICIENT_EVIDENCE" not in assistant["content"]


def test_llm_failure_stores_nothing(client, corpus):
    """A failed call must not leave a dangling question in the transcript."""
    app.dependency_overrides[get_llm_provider] = lambda: BrokenLLM()
    conversation = open_conversation(client, corpus["project_id"])
    try:
        response = client.post(
            f"/conversations/{conversation['id']}/messages",
            json={"query": "how do gradients flow in deep networks?"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    assert response.status_code == 503
    assert "provider unavailable" in response.json()["detail"]
    assert client.get(f"/conversations/{conversation['id']}/messages").json() == []


def test_messages_require_a_real_conversation(client):
    response = client.get(f"/conversations/{uuid4()}/messages")
    assert response.status_code == 404
