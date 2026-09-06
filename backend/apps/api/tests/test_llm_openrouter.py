"""OpenRouter provider tests.

The provider's own logic (headers, error surfacing, malformed responses) is
tested offline against a stubbed transport — those paths must be reliable
precisely when the network is not.

The one test that calls the real API is skipped unless OPENROUTER_API_KEY is
configured, so the suite stays runnable offline and free. It is *not* deleted:
PRD Section 9 forbids claiming a provider works without running it, and this is
the only test that proves the configured model actually exists and answers.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.services.llm import (
    LLMConfigurationError,
    LLMError,
    OpenRouterProvider,
)


def build(transport: httpx.MockTransport | None = None, **overrides):
    kwargs = {
        "api_key": "test-key",
        "model": "test/model",
        "base_url": "https://openrouter.test/api/v1",
        "temperature": 0.0,
        "max_output_tokens": 256,
        "timeout": 5.0,
        "app_title": "Test App",
        "app_url": "http://localhost:3000",
    }
    kwargs.update(overrides)
    return OpenRouterProvider(**kwargs)


def respond(monkeypatch, handler):
    """Route the provider's httpx.post through a mock transport."""

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url, **{
            k: v for k, v in kwargs.items() if k in ("headers", "json")
        })
        return handler(request)

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)


def ok_response(request):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "  Depth helps [E1].  "}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 12},
        },
        request=request,
    )


def test_missing_api_key_is_a_configuration_error():
    """A missing key must not surface as a generic 500 later on."""
    with pytest.raises(LLMConfigurationError) as exc:
        build(api_key="")

    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_completion_is_returned_stripped(monkeypatch):
    respond(monkeypatch, ok_response)

    assert build().complete(system="s", prompt="p") == "Depth helps [E1]."


def test_request_carries_auth_model_and_messages(monkeypatch):
    captured = {}

    def handler(request):
        captured["headers"] = request.headers
        captured["body"] = __import__("json").loads(request.content)
        return ok_response(request)

    respond(monkeypatch, handler)
    build().complete(system="the rules", prompt="the question")

    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["headers"]["x-title"] == "Test App"
    body = captured["body"]
    assert body["model"] == "test/model"
    # Temperature 0: grounding is constraint-following, not generation.
    assert body["temperature"] == 0.0
    assert body["messages"] == [
        {"role": "system", "content": "the rules"},
        {"role": "user", "content": "the question"},
    ]


def test_image_completion_is_single_bounded_multimodal_request(monkeypatch):
    captured = {}

    def handler(request):
        captured["body"] = __import__("json").loads(request.content)
        return ok_response(request)

    respond(monkeypatch, handler)
    result = build(max_output_tokens=1024).complete_with_image(
        system="interpret conservatively",
        prompt="caption and page context",
        image=b"\x89PNG\r\nfigure",
        media_type="image/png",
        max_output_tokens=500,
    )

    assert result == "Depth helps [E1]."
    body = captured["body"]
    assert body["max_tokens"] == 500
    assert len(body["messages"]) == 2
    content = body["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "caption and page context"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith(
        "data:image/png;base64,iVBORw0K"
    )


def test_provider_error_message_is_surfaced(monkeypatch):
    """PRD Section 9: 'LLM call failed' alone is not diagnosable."""
    respond(
        monkeypatch,
        lambda request: httpx.Response(
            402,
            json={"error": {"message": "Insufficient credits"}},
            request=request,
        ),
    )

    with pytest.raises(LLMError) as exc:
        build().complete(system="s", prompt="p")

    assert "402" in str(exc.value)
    assert "Insufficient credits" in str(exc.value)


def test_network_failure_is_surfaced(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr("app.services.llm.httpx.post", boom)

    with pytest.raises(LLMError) as exc:
        build().complete(system="s", prompt="p")

    assert "timed out" in str(exc.value)


def test_malformed_response_is_rejected(monkeypatch):
    """A shape change must fail loudly, not yield an empty 'answer'."""
    respond(
        monkeypatch,
        lambda request: httpx.Response(200, json={"unexpected": True}, request=request),
    )

    with pytest.raises(LLMError) as exc:
        build().complete(system="s", prompt="p")

    assert "unreadable" in str(exc.value)


def test_empty_completion_is_rejected(monkeypatch):
    respond(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "   "}}]}, request=request
        ),
    )

    with pytest.raises(LLMError):
        build().complete(system="s", prompt="p")


# === The live call ==========================================================

live = pytest.mark.skipif(
    not get_settings().openrouter_api_key,
    reason="OPENROUTER_API_KEY not configured — live provider check skipped.",
)


@live
def test_live_openrouter_model_answers_and_obeys_evidence_ids():
    """Proves the configured model exists, responds, and can follow the rules.

    Asserts only what a correct model must do — it cites the block it was given
    and does not invent one. Anything stricter would be testing the model's
    prose rather than our contract with it.
    """
    from app.services.answering import SYSTEM_PROMPT, USER_PROMPT, extract_cited_ids
    from app.services.llm import build_llm_provider

    evidence = (
        '<EVIDENCE id="E1" paper="Deep Residual Learning" page="1" '
        'section="1 Introduction">\n'
        "Residual connections let gradients flow through very deep networks and "
        "make optimization of hundreds of layers tractable in practice.\n"
        "</EVIDENCE>"
    )

    answer = build_llm_provider().complete(
        system=SYSTEM_PROMPT,
        prompt=USER_PROMPT.format(
            question="How do residual connections help optimization?",
            evidence=evidence,
        ),
    )

    assert answer.strip()
    assert extract_cited_ids(answer) == ["E1"]


@live
def test_live_openrouter_declines_when_evidence_is_missing():
    """PRD 5.4: the model must say so rather than answer from its own knowledge.

    The evidence below is deliberately about something else entirely, and the
    question has a well-known answer the model certainly holds in its weights.
    """
    from app.services.answering import (
        INSUFFICIENT_MARKER,
        SYSTEM_PROMPT,
        USER_PROMPT,
    )
    from app.services.llm import build_llm_provider

    evidence = (
        '<EVIDENCE id="E1" page="2" section="2 Tokenization">\n'
        "Subword tokenization splits rare words into smaller units so the model "
        "vocabulary stays bounded while still covering unseen terms.\n"
        "</EVIDENCE>"
    )

    answer = build_llm_provider().complete(
        system=SYSTEM_PROMPT,
        prompt=USER_PROMPT.format(
            question="What is the capital city of France?", evidence=evidence
        ),
    )

    assert answer.strip().upper().startswith(INSUFFICIENT_MARKER), answer
    assert "Paris" not in answer
