"""Cross-paper agreement matrix (PRD Phase 4).

The property that matters: each cell is judged against *that paper's* evidence
only. A matrix built from project-wide retrieval would show three papers
agreeing when only one of them mentioned the claim at all.
"""

import pytest

from app.api.answer import get_llm_provider
from main import app
from tests.fixtures import build_pdf
from tests.test_answering import ScriptedLLM

SUPPORTING_PAGES = [
    [
        "Abstract",
        "",
        "We find that residual connections reduce training error as depth",
        "increases, and that very deep networks become straightforward to train.",
    ]
]

UNRELATED_PAGES = [
    [
        "Abstract",
        "",
        "We study subword tokenization and show that vocabulary size can be",
        "bounded while still covering rare and unseen terms in the corpus.",
    ]
]


def upload(client, project_id, name, pages):
    response = client.post(
        f"/projects/{project_id}/papers",
        files={
            "file": (
                name,
                build_pdf(pages, title=name, author="Tester"),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    paper = client.get(f"/papers/{response.json()['id']}").json()
    assert paper["status"] == "ready", paper["job"]
    return paper


@pytest.fixture
def two_papers(client, project):
    return {
        "project_id": project["id"],
        "supporting": upload(client, project["id"], "residual.pdf", SUPPORTING_PAGES),
        "unrelated": upload(client, project["id"], "tokens.pdf", UNRELATED_PAGES),
    }


@pytest.fixture
def scripted():
    def use(reply: str) -> ScriptedLLM:
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm_provider] = lambda: llm
        return llm

    yield use
    app.dependency_overrides.pop(get_llm_provider, None)


@pytest.fixture
def claim(client, project):
    response = client.post(
        f"/projects/{project['id']}/claims",
        json={"text": "Residual connections reduce training error as depth increases."},
    )
    assert response.status_code == 201
    return response.json()


def test_matrix_judges_each_paper_against_its_own_evidence(
    client, two_papers, claim, scripted
):
    llm = scripted(
        "VERDICT: SUPPORTED\nCONFIDENCE: 80\nREASONING: Stated in the paper [E1]."
    )

    response = client.post(
        f"/projects/{two_papers['project_id']}/cross-paper",
        json={
            "claim_ids": [claim["id"]],
            "paper_ids": [two_papers["supporting"]["id"], two_papers["unrelated"]["id"]],
        },
    )
    assert response.status_code == 200, response.text
    matrix = response.json()

    assert matrix["cells_computed"] == 2
    assert llm.calls == 2, "one model call per cell, not one for the whole matrix"

    # Each cell's evidence must come from its own paper — that is what makes
    # the matrix meaningful rather than the same verdict repeated.
    for cell in matrix["cells"]:
        for citation in cell["verification"]["citations"]:
            assert citation["paper_id"] == cell["paper_id"]


def test_stored_cells_are_reused_instead_of_re_billed(client, two_papers, claim, scripted):
    llm = scripted("VERDICT: SUPPORTED\nCONFIDENCE: 80\nREASONING: Stated [E1].")
    body = {
        "claim_ids": [claim["id"]],
        "paper_ids": [two_papers["supporting"]["id"]],
    }

    first = client.post(f"/projects/{two_papers['project_id']}/cross-paper", json=body)
    assert first.json()["cells_computed"] == 1
    calls_after_first = llm.calls

    second = client.post(f"/projects/{two_papers['project_id']}/cross-paper", json=body)
    assert second.json()["cells_computed"] == 0
    assert llm.calls == calls_after_first, "a cached cell must not call the model"
    assert second.json()["cells"][0]["verification"]["verdict"] == "supported"


def test_refresh_recomputes_stored_cells(client, two_papers, claim, scripted):
    scripted("VERDICT: SUPPORTED\nCONFIDENCE: 80\nREASONING: Stated [E1].")
    body = {
        "claim_ids": [claim["id"]],
        "paper_ids": [two_papers["supporting"]["id"]],
    }
    client.post(f"/projects/{two_papers['project_id']}/cross-paper", json=body)

    scripted("VERDICT: CONTRADICTED\nCONFIDENCE: 55\nREASONING: Reread it [E1].")
    refreshed = client.post(
        f"/projects/{two_papers['project_id']}/cross-paper",
        json={**body, "refresh": True},
    )
    assert refreshed.json()["cells_computed"] == 1
    assert refreshed.json()["cells"][0]["verification"]["verdict"] == "contradicted"


def test_matrix_size_is_capped(client, two_papers, claim):
    """Each cell is a model call, so the cap is a spend limit, not a UI hint."""
    response = client.post(
        f"/projects/{two_papers['project_id']}/cross-paper",
        json={
            "claim_ids": [claim["id"]] * 6,
            "paper_ids": [two_papers["supporting"]["id"]],
        },
    )
    assert response.status_code == 422  # rejected by the schema's max_length


def test_stored_matrix_endpoint_spends_nothing(client, two_papers, claim, scripted):
    llm = scripted("VERDICT: SUPPORTED\nCONFIDENCE: 80\nREASONING: Stated [E1].")
    client.post(
        f"/projects/{two_papers['project_id']}/cross-paper",
        json={
            "claim_ids": [claim["id"]],
            "paper_ids": [two_papers["supporting"]["id"]],
        },
    )
    calls = llm.calls

    stored = client.get(
        f"/projects/{two_papers['project_id']}/cross-paper",
        params={
            "claim_ids": [claim["id"]],
            "paper_ids": [two_papers["supporting"]["id"]],
        },
    )
    assert stored.status_code == 200
    assert len(stored.json()["cells"]) == 1
    assert llm.calls == calls


def test_matrix_rejects_papers_from_another_project(client, two_papers, claim):
    from uuid import uuid4

    response = client.post(
        f"/projects/{two_papers['project_id']}/cross-paper",
        json={"claim_ids": [claim["id"]], "paper_ids": [str(uuid4())]},
    )
    assert response.status_code == 404
