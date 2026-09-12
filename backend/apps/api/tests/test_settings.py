"""Runtime settings.

Two properties matter: a stored override actually changes retrieval behaviour
(otherwise the settings page is decoration), and the API key never leaves the
process (PRD Section 9).
"""

import pytest

from app.services.settings_store import get_effective_settings, update_settings


@pytest.fixture(autouse=True)
def restore_defaults():
    """Settings are global, so every test puts them back."""
    yield
    update_settings(dict.fromkeys(
        ("search_top_k", "rerank_top_k", "context_max_tokens", "llm_model")
    ))


def test_defaults_come_from_the_environment(client):
    response = client.get("/settings")
    assert response.status_code == 200

    body = response.json()
    assert body["search_top_k"] == 20
    assert body["rerank_top_k"] == 6
    assert body["embedding_model"] == "jinaai/jina-embeddings-v2-small-en"
    assert body["overridden"] == []


def test_credentials_are_reported_as_flags_never_values(client):
    body = client.get("/settings").json()

    assert body["llm_key_configured"] is True or body["llm_key_configured"] is False

    # Anything credential-shaped must be a boolean, never the secret itself.
    # Matched on name segments, so "context_max_tokens" is not a credential.
    credential_words = {"key", "token", "secret", "password"}
    sensitive = [
        key for key in body if credential_words & set(key.split("_"))
    ]
    assert sensitive, "the page needs to know whether credentials are configured"
    for key in sensitive:
        assert isinstance(body[key], bool), f"{key} exposes a value, not a flag"


def test_override_is_stored_and_reported(client):
    response = client.patch("/settings", json={"search_top_k": 42})
    assert response.status_code == 200

    body = response.json()
    assert body["search_top_k"] == 42
    assert "search_top_k" in body["overridden"]
    # Untouched fields keep their environment values.
    assert body["rerank_top_k"] == 6


def test_override_changes_what_retrieval_actually_uses(client):
    client.patch("/settings", json={"search_top_k": 3})
    assert get_effective_settings().search_top_k == 3

    client.patch("/settings", json={"search_top_k": None})
    assert get_effective_settings().search_top_k == 20


def test_out_of_range_values_are_rejected(client):
    assert client.patch("/settings", json={"rerank_top_k": 999}).status_code == 422
    assert client.patch("/settings", json={"search_top_k": 0}).status_code == 422


def test_unset_fields_are_left_alone(client):
    client.patch("/settings", json={"search_top_k": 11})
    body = client.patch("/settings", json={"rerank_top_k": 4}).json()

    assert body["search_top_k"] == 11, "a partial update must not clear other fields"
    assert body["rerank_top_k"] == 4
