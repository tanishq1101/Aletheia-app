"""Reproducibility disclosure audit (PRD Phase 6, disclosure scope).

The score must reflect what the paper actually discloses, so the tests pin the
two things that make it defensible: an unreadable model reply counts as MISSING
rather than a pass, and a GitHub lookup that fails is reported rather than
silently dropped. Network access is never required — the lookup is off by
default in tests and stubbed where it is exercised.
"""

from uuid import uuid4

import httpx
import pytest

from app.api.answer import get_llm_provider
from app.services import reproducibility as repro
from app.services.reproducibility import (
    DISCLOSED,
    MISSING,
    extract_links,
    fetch_github_metadata,
    parse_audit,
)
from main import app
from tests.fixtures import build_pdf
from tests.test_answering import ScriptedLLM

REPRO_PAGES = [
    [
        "Abstract",
        "",
        "We train a residual network on ImageNet and release our implementation",
        "at https://github.com/example-org/resnet-repro for others to use.",
    ],
    [
        "3 Experiments",
        "",
        "All models are trained with SGD, a learning rate of 0.1, batch size 256,",
        "and weight decay of 0.0001 on eight GPUs for ninety epochs.",
    ],
]


@pytest.fixture
def paper(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={
            "file": (
                "repro.pdf",
                build_pdf(REPRO_PAGES, title="Repro Paper", author="Tester"),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    created = client.get(f"/papers/{response.json()['id']}").json()
    assert created["status"] == "ready", created["job"]
    return created


@pytest.fixture
def scripted():
    def use(reply: str) -> ScriptedLLM:
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm_provider] = lambda: llm
        return llm

    yield use
    app.dependency_overrides.pop(get_llm_provider, None)


# === Link extraction and parsing (no model, no network) =====================


def test_links_are_read_from_the_papers_own_text():
    links = extract_links(
        "Code at https://github.com/example-org/resnet-repro. "
        "See also https://doi.org/10.1234/abcd.5678 and "
        "https://gitlab.com/group/project."
    )

    kinds = {link["kind"] for link in links}
    assert kinds == {"github", "doi", "gitlab"}

    github = next(link for link in links if link["kind"] == "github")
    assert github["owner"] == "example-org"
    assert github["repo"] == "resnet-repro"


def test_duplicate_links_are_reported_once():
    text = "https://github.com/a/b and again https://github.com/a/b"
    assert len(extract_links(text)) == 1


def test_parse_audit_reads_the_required_format():
    status, rationale = parse_audit(
        "STATUS: DISCLOSED\nFINDING: Hyperparameters are listed [E1]."
    )
    assert status == DISCLOSED
    assert rationale == "Hyperparameters are listed [E1]."


def test_unreadable_audit_reply_counts_as_missing():
    """An unparseable reply must never inflate the score."""
    status, _ = parse_audit("Looks fine to me.")
    assert status == MISSING


# === GitHub lookup (stubbed transport, never a live call) ===================


def test_github_metadata_is_summarised(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "full_name": "example-org/resnet-repro",
                "html_url": "https://github.com/example-org/resnet-repro",
                "stargazers_count": 1234,
                "license": {"spdx_id": "MIT"},
                "pushed_at": "2026-01-05T00:00:00Z",
                "language": "Python",
            },
        )

    monkeypatch.setattr(repro.httpx, "get", fake_get)
    metadata = fetch_github_metadata("example-org", "resnet-repro")

    assert metadata["status"] == "ok"
    assert metadata["stars"] == 1234
    assert metadata["license"] == "MIT"


@pytest.mark.parametrize(
    ("code", "expected"),
    [(404, "not_found"), (403, "rate_limited"), (500, "unavailable")],
)
def test_github_failures_are_reported_not_swallowed(monkeypatch, code, expected):
    monkeypatch.setattr(
        repro.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            code, request=httpx.Request("GET", url), json={}
        ),
    )
    assert fetch_github_metadata("a", "b")["status"] == expected


def test_github_network_error_does_not_raise(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(repro.httpx, "get", boom)
    assert fetch_github_metadata("a", "b")["status"] == "unavailable"


# === The report through the API =============================================


def test_report_is_computed_stored_and_read_back(client, paper, scripted):
    scripted("STATUS: DISCLOSED\nFINDING: The paper states this [E1].")

    response = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    )
    assert response.status_code == 200, response.text
    report = response.json()

    assert len(report["checks"]) == len(repro.DIMENSIONS)
    assert report["score"] == pytest.approx(1.0)
    assert all(check["citations"] for check in report["checks"])

    # A link in the paper's text is found without any model involvement.
    assert any(link["kind"] == "github" for link in report["links"])
    # check_github=False means no lookup was attempted, and nothing invented.
    assert report["repo_metadata"] is None

    stored = client.get(f"/papers/{paper['id']}/reproducibility").json()
    assert stored["score"] == report["score"]
    assert len(stored["checks"]) == len(report["checks"])


def test_missing_disclosure_scores_zero(client, paper, scripted):
    scripted("STATUS: MISSING\nFINDING: The evidence does not address this.")

    report = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    ).json()

    assert report["score"] == pytest.approx(0.0)
    assert all(check["status"] == MISSING for check in report["checks"])


def test_partial_disclosure_scores_between(client, paper, scripted):
    scripted("STATUS: PARTIAL\nFINDING: Mentioned but underspecified [E1].")

    report = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    ).json()

    assert 0.0 < report["score"] < 1.0


def test_rerunning_replaces_the_previous_report(client, paper, scripted):
    scripted("STATUS: DISCLOSED\nFINDING: Stated [E1].")
    first = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    ).json()

    scripted("STATUS: MISSING\nFINDING: Not addressed.")
    second = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    ).json()

    assert second["id"] == first["id"]
    assert second["score"] < first["score"]
    assert len(second["checks"]) == len(repro.DIMENSIONS), "no stale checks left over"


def test_fabricated_citations_never_reach_a_check(client, paper, scripted):
    scripted("STATUS: DISCLOSED\nFINDING: Stated [E1] and in appendix C [E88].")

    report = client.post(
        f"/papers/{paper['id']}/reproducibility", json={"check_github": False}
    ).json()

    for check in report["checks"]:
        assert "E88" not in check["rationale"]
        assert all(c["evidence_id"] != "E88" for c in check["citations"])


def test_report_is_null_before_any_audit(client, paper):
    assert client.get(f"/papers/{paper['id']}/reproducibility").json() is None


def test_report_requires_a_real_paper(client):
    assert client.get(f"/papers/{uuid4()}/reproducibility").status_code == 404
