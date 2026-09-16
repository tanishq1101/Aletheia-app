"""PDF export endpoints.

These render a result the caller already holds. The properties worth pinning
are that they cost no model call, that ownership is still enforced through the
path, and that a body naming a different resource cannot be rendered under a
path the caller happens to own.
"""

from uuid import uuid4

import pymupdf
import pytest

from app.core import rate_limit

from .fixtures import build_pdf
from .test_report import answer, run


def _answer_body(**overrides):
    payload = {"question": "What BLEU is reported?",
               "answer": answer().model_dump(mode="json"),
               "project_name": "Reading list"}
    payload.update(overrides)
    return payload


def text_of(response) -> str:
    with pymupdf.open(stream=response.content, filetype="pdf") as opened:
        return " ".join(page.get_text() for page in opened)


def test_an_answer_renders_as_a_downloadable_pdf(client, project):
    response = client.post(
        f"/projects/{project['id']}/reports/ask.pdf", json=_answer_body())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    assert "what-bleu-is-reported" in disposition
    assert "41.8" in text_of(response)


def test_a_report_is_not_cached_between_users(client, project):
    """The document is built from one person's library."""
    response = client.post(
        f"/projects/{project['id']}/reports/ask.pdf", json=_answer_body())
    assert "no-store" in response.headers["cache-control"]


def test_a_research_brief_renders_as_a_downloadable_pdf(client, project):
    response = client.post(f"/projects/{project['id']}/reports/brief.pdf",
                           json={"run": run().model_dump(mode="json")})

    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")
    assert "How this brief was built" in text_of(response)


def test_a_report_for_an_unknown_project_is_a_404(client):
    response = client.post(
        f"/projects/{uuid4()}/reports/ask.pdf", json=_answer_body())
    assert response.status_code == 404


@pytest.fixture
def paper(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("repro.pdf", build_pdf(["Reproducibility. We release code."],
                                               title="Repro Paper"),
                        "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return client.get(f"/papers/{response.json()['id']}").json()


def test_a_disclosure_report_renders_for_the_paper_in_the_path(client, paper):
    from .test_report import _report

    response = client.post(
        f"/papers/{paper['id']}/reports/disclosure.pdf",
        json={"report": _report(paper_id=paper["id"]).model_dump(mode="json"),
              "paper_title": "Repro Paper"},
    )
    assert response.status_code == 200, response.text
    assert "Nothing here executed" in " ".join(text_of(response).split())


def test_a_disclosure_report_must_match_the_paper_in_the_path(client, paper):
    """Ownership is checked against the *path* id. Rendering a body that names
    a different paper under it would export a report the caller was never
    authorised for."""
    from .test_report import _report

    response = client.post(
        f"/papers/{paper['id']}/reports/disclosure.pdf",
        json={"report": _report(paper_id=str(uuid4())).model_dump(mode="json"),
              "paper_title": "Somebody else's paper"},
    )
    assert response.status_code == 400, response.text
    assert "different paper" in response.json()["detail"]


def test_a_malformed_result_is_rejected_rather_than_rendered_blank(client, project):
    response = client.post(f"/projects/{project['id']}/reports/ask.pdf",
                           json={"question": "q"})
    assert response.status_code == 422


def test_exporting_a_report_does_not_spend_the_ai_request_budget():
    """Rendering calls no model. Sharing the much smaller AI budget would mean
    downloading a brief you already paid for could block asking a question."""
    for path in ("/projects/x/reports/ask.pdf",
                 "/projects/x/reports/brief.pdf",
                 "/papers/x/reports/disclosure.pdf"):
        assert not any(marker in path for marker in rate_limit.LLM_PATH_MARKERS), (
            f"{path} collides with an LLM rate-limit marker"
        )


def test_the_chosen_filename_survives_a_cross_origin_download(client, project):
    """A browser hides every response header from JavaScript except the six
    CORS-safelisted ones. Without Content-Disposition exposed, the client
    cannot read the name the server chose and every report saves under the
    same generic fallback — which is what happened before this was added."""
    response = client.post(
        f"/projects/{project['id']}/reports/ask.pdf",
        json=_answer_body(),
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200, response.text
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "content-disposition" in exposed.lower(), exposed
