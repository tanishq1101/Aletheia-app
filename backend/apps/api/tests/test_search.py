"""Retrieval tests.

Uses a corpus of deliberately distinct topics so a hit can be judged right or
wrong, rather than merely "some rows came back".
"""

from uuid import uuid4

import pytest

from app.db.session import get_connection
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


@pytest.fixture
def corpus(client, project):
    """A processed paper whose pages cover clearly different topics."""
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


def search(client, project_id, query, **kwargs):
    return client.post(
        f"/projects/{project_id}/search", json={"query": query, **kwargs}
    )


def test_chunks_and_embeddings_are_stored(client, corpus):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS n,
                   count(embedding) AS vectors,
                   count(DISTINCT embedding_model) AS models,
                   count(page_id) AS with_page
              FROM paper_chunks WHERE paper_id = %s
            """,
            (corpus["paper_id"],),
        )
        row = cur.fetchone()

    assert row["n"] > 0
    # Every chunk embedded, none left half-processed.
    assert row["vectors"] == row["n"]
    assert row["models"] == 1
    # chunk -> page -> paper must resolve for citations (PRD 5.2).
    assert row["with_page"] == row["n"]


def test_stored_vectors_have_the_schema_dimensionality(client, corpus):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT vector_dims(embedding) AS d FROM paper_chunks"
            " WHERE paper_id = %s",
            (corpus["paper_id"],),
        )
        assert [r["d"] for r in cur.fetchall()] == [512]


def test_search_returns_the_topically_correct_chunk(client, corpus):
    response = search(client, corpus["project_id"], "how do gradients flow in deep nets?")

    assert response.status_code == 200, response.text
    results = response.json()
    assert results
    # The optimization page should win over tokenization and evaluation.
    assert "Residual connections" in results[0]["content"]
    assert results[0]["page_number"] == 1


def test_search_distinguishes_between_topics(client, corpus):
    tokenization = search(client, corpus["project_id"], "splitting rare words into subwords")
    evaluation = search(client, corpus["project_id"], "precision and recall against baselines")

    assert tokenization.json()[0]["page_number"] == 2
    assert evaluation.json()[0]["page_number"] == 3


def test_results_are_ordered_by_similarity(client, corpus):
    results = search(client, corpus["project_id"], "deep network optimization").json()

    scores = [r["similarity"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 <= s <= 1.0 for s in scores)


def test_results_carry_citation_metadata(client, corpus):
    top = search(client, corpus["project_id"], "residual connections").json()[0]

    # Everything a citation needs to say "Section X, page N of <paper>".
    assert top["page_number"] is not None
    assert top["section"] is not None
    assert top["paper_id"] == corpus["paper_id"]
    assert top["filename"] == "topics.pdf"
    assert top["chunk_id"]
    assert top["token_count"] > 0


def test_top_k_is_respected(client, corpus):
    results = search(client, corpus["project_id"], "networks", top_k=2).json()

    assert len(results) <= 2


def test_search_is_scoped_to_the_project(client, corpus):
    other = client.post("/projects", json={"name": "Unrelated"}).json()
    try:
        results = search(client, other["id"], "residual connections").json()
        # The corpus lives in a different project, so nothing should match.
        assert results == []
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (other["id"],))
            conn.commit()


def test_search_on_unknown_project_is_404(client):
    assert search(client, uuid4(), "anything").status_code == 404


def test_empty_query_is_rejected(client, project):
    assert search(client, project["id"], "").status_code == 422


def test_reprocess_does_not_duplicate_chunks(client, corpus):
    def chunk_count():
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM paper_chunks WHERE paper_id = %s",
                (corpus["paper_id"],),
            )
            return cur.fetchone()["n"]

    before = chunk_count()
    client.post(f"/papers/{corpus['paper_id']}/reprocess")
    client.post(f"/papers/{corpus['paper_id']}/reprocess")

    assert chunk_count() == before


def test_search_still_works_after_reprocess(client, corpus):
    client.post(f"/papers/{corpus['paper_id']}/reprocess")

    results = search(client, corpus["project_id"], "gradients in deep networks").json()

    assert results
    assert "Residual connections" in results[0]["content"]
