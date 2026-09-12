"""Claim verification (PRD Phase 3, Section 4).

The LLM is scripted, as in test_answering.py: the properties under test belong
to the backend — a verdict may only cite evidence the backend issued, an
unparseable reply must not become a confident verdict, and "insufficient" is a
real outcome rather than an error.
"""

from uuid import uuid4

import pytest

from app.api.answer import get_llm_provider
from app.services.verification import (
    CONTRADICTED,
    INSUFFICIENT,
    SUPPORTED,
    extract_claims,
    parse_verdict,
)
from main import app
from tests.fixtures import build_pdf
from tests.test_answering import ScriptedLLM

CLAIM_PAGES = [
    [
        "Abstract",
        "",
        "We show that residual connections let gradients flow through very deep",
        "networks, and that networks of over one hundred layers can be optimized",
        "in practice as a result.",
    ],
    [
        "4 Conclusion",
        "",
        "Residual learning reduces training error as depth increases, reversing",
        "the degradation observed in plain deep networks on the same data.",
    ],
]


@pytest.fixture
def paper(client, project):
    response = client.post(
        f"/projects/{project['id']}/papers",
        files={
            "file": (
                "claims.pdf",
                build_pdf(CLAIM_PAGES, title="Residual Claims", author="Tester"),
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


# === Reply parsing (no database, no model) ==================================


def test_parse_verdict_reads_the_required_format():
    verdict, confidence, rationale = parse_verdict(
        "VERDICT: SUPPORTED\nCONFIDENCE: 82\nREASONING: The paper states it [E1]."
    )

    assert verdict == SUPPORTED
    assert confidence == 0.82
    assert rationale == "The paper states it [E1]."


def test_parse_verdict_handles_contradiction_and_clamps_confidence():
    verdict, confidence, _ = parse_verdict(
        "VERDICT: CONTRADICTED\nCONFIDENCE: 140\nREASONING: The opposite [E2]."
    )

    assert verdict == CONTRADICTED
    assert confidence == 1.0


def test_unparseable_reply_becomes_insufficient_not_a_guess():
    """A confident-looking wrong verdict is the failure worth designing against."""
    verdict, confidence, rationale = parse_verdict("I think this is probably true.")

    assert verdict == INSUFFICIENT
    assert confidence is None
    assert "probably true" in rationale


def test_extract_claims_strips_bullets_and_drops_fragments():
    llm = ScriptedLLM(
        "- Residual connections reduce training error as depth increases.\n"
        "2. Networks over one hundred layers can be optimized in practice.\n"
        "too short\n"
        "- Residual connections reduce training error as depth increases.\n"
    )

    claims = extract_claims(text="some paper text", llm=llm, limit=8)

    assert claims == [
        "Residual connections reduce training error as depth increases.",
        "Networks over one hundred layers can be optimized in practice.",
    ]


# === Extraction and verification through the API =============================


def test_claims_are_extracted_and_listed(client, paper, scripted):
    scripted(
        "Residual connections let gradients flow through very deep networks.\n"
        "Residual learning reduces training error as depth increases.\n"
    )

    response = client.post(f"/papers/{paper['id']}/claims/extract", json={"limit": 5})
    assert response.status_code == 201, response.text
    extracted = response.json()
    assert len(extracted) == 2
    assert [c["claim_index"] for c in extracted] == [0, 1]
    assert all(c["source"] == "extracted" for c in extracted)

    listed = client.get(f"/papers/{paper['id']}/claims").json()
    assert [c["text"] for c in listed] == [c["text"] for c in extracted]
    # Nothing has been checked yet, and the UI must not imply otherwise.
    assert all(c["verification"] is None for c in listed)


def test_re_extracting_replaces_the_previous_set(client, paper, scripted):
    scripted("Residual connections let gradients flow through deep networks.\n")
    client.post(f"/papers/{paper['id']}/claims/extract", json={"limit": 5})

    scripted("Residual learning reduces training error as depth increases.\n")
    client.post(f"/papers/{paper['id']}/claims/extract", json={"limit": 5})

    listed = client.get(f"/papers/{paper['id']}/claims").json()
    assert len(listed) == 1
    assert "training error" in listed[0]["text"]


def test_verification_stores_verdict_and_resolved_citations(client, paper, scripted):
    scripted("Residual connections let gradients flow through deep networks.\n")
    claim = client.post(
        f"/papers/{paper['id']}/claims/extract", json={"limit": 5}
    ).json()[0]

    scripted(
        "VERDICT: SUPPORTED\nCONFIDENCE: 88\n"
        "REASONING: The abstract states this directly [E1]."
    )
    response = client.post(f"/claims/{claim['id']}/verify")
    assert response.status_code == 200, response.text

    verification = response.json()
    assert verification["verdict"] == SUPPORTED
    assert verification["confidence"] == pytest.approx(0.88)
    assert verification["evidence_count"] > 0
    assert verification["citations"], "a verdict must show the evidence behind it"
    assert verification["citations"][0]["location"]

    # The verdict travels with the claim when the page is reloaded.
    listed = client.get(f"/papers/{paper['id']}/claims").json()
    assert listed[0]["verification"]["verdict"] == SUPPORTED


def test_re_verifying_replaces_the_previous_verdict(client, paper, scripted):
    scripted("Residual connections let gradients flow through deep networks.\n")
    claim = client.post(
        f"/papers/{paper['id']}/claims/extract", json={"limit": 5}
    ).json()[0]

    scripted("VERDICT: SUPPORTED\nCONFIDENCE: 88\nREASONING: Stated directly [E1].")
    first = client.post(f"/claims/{claim['id']}/verify").json()

    scripted("VERDICT: CONTRADICTED\nCONFIDENCE: 40\nREASONING: Reread it [E1].")
    second = client.post(f"/claims/{claim['id']}/verify").json()

    assert second["verdict"] == CONTRADICTED
    listed = client.get(f"/papers/{paper['id']}/claims").json()
    assert listed[0]["verification"]["id"] == first["id"] == second["id"]


def test_fabricated_citations_never_reach_a_verdict(client, paper, scripted):
    """PRD Section 12 applies to verdicts exactly as it does to answers."""
    scripted("Residual connections let gradients flow through deep networks.\n")
    claim = client.post(
        f"/papers/{paper['id']}/claims/extract", json={"limit": 5}
    ).json()[0]

    scripted(
        "VERDICT: SUPPORTED\nCONFIDENCE: 90\n"
        "REASONING: Stated in the abstract [E1] and confirmed in table 9 [E77]."
    )
    verification = client.post(f"/claims/{claim['id']}/verify").json()

    assert "E77" not in verification["rationale"]
    assert all(c["evidence_id"] != "E77" for c in verification["citations"])


def test_manual_claim_can_be_verified(client, project, paper, scripted):
    created = client.post(
        f"/projects/{project['id']}/claims",
        json={"text": "Deeper plain networks always train better than shallow ones."},
    )
    assert created.status_code == 201, created.text
    claim = created.json()
    assert claim["source"] == "manual"

    scripted(
        "VERDICT: CONTRADICTED\nCONFIDENCE: 75\n"
        "REASONING: The paper reports the opposite [E1]."
    )
    verification = client.post(f"/claims/{claim['id']}/verify").json()
    assert verification["verdict"] == CONTRADICTED


def test_extraction_refuses_a_paper_with_no_text(client, project):
    """Extracting from an empty paper would invent claims from nothing."""
    from tests.conftest import MINIMAL_PDF

    response = client.post(
        f"/projects/{project['id']}/papers",
        files={"file": ("blank.pdf", MINIMAL_PDF, "application/pdf")},
    )
    paper_id = response.json()["id"]

    failed = client.post(f"/papers/{paper_id}/claims/extract", json={"limit": 3})
    assert failed.status_code == 409
    assert "no extracted text" in failed.json()["detail"].lower()


def test_verify_requires_a_real_claim(client):
    assert client.post(f"/claims/{uuid4()}/verify").status_code == 404
