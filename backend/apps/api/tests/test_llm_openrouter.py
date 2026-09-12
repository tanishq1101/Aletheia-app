"""OpenAI-compatible provider tests.

The provider's own logic (headers, error surfacing, malformed responses) is
tested offline against a stubbed transport — those paths must be reliable
precisely when the network is not.

The real-provider tests are skipped unless GEMINI_API_KEY is
configured, so the suite stays runnable offline and free. It is *not* deleted:
PRD Section 9 forbids claiming a provider works without running it, and this is
the only test that proves the configured model actually exists and answers.
"""

import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.llm import (
    FallbackLLMProvider,
    LLMConfigurationError,
    LLMError,
    OpenRouterProvider,
    build_llm_provider,
    configured_llm_model,
)


class StubProvider:
    """Small provider double for failover behavior; makes no HTTP request."""

    supports_images = True

    def __init__(self, name: str, reply: str | Exception):
        self.name = name
        self.reply = reply
        self.calls = 0

    def complete(self, *, system: str, prompt: str) -> str:
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def complete_with_image(self, **kwargs) -> str:
        return self.complete(system=kwargs["system"], prompt=kwargs["prompt"])


def test_openai_failure_retries_the_same_prompt_with_gemini_backup():
    primary = StubProvider("gpt-4.1-mini", LLMError("temporary outage"))
    backup = StubProvider("gemini-2.5-flash", "Grounded answer [E1].")
    provider = FallbackLLMProvider(primary, backup)

    assert provider.complete(system="rules", prompt="evidence") == "Grounded answer [E1]."
    assert primary.calls == 1
    assert backup.calls == 1
    # The stub's own name, so the caller can see which provider actually
    # answered — unrelated to the configured gemini profile.
    assert provider.name == "gemini-2.5-flash"


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
    not get_settings().gemini_api_key,
    reason="GEMINI_API_KEY not configured — live provider checks skipped.",
)


@live
def test_live_gemini_model_answers_and_obeys_evidence_ids():
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
def test_live_gemini_declines_when_evidence_is_missing():
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


# --- Budget-aware retry ------------------------------------------------------
# `max_tokens` is a reservation, not a spend. OpenRouter refuses the whole
# request with 402 when the balance cannot cover the ceiling, even though the
# answer would cost a fraction of it — which took out every AI feature at once.


def _payment_required(affordable: int):
    def handler(request):
        return httpx.Response(
            402,
            json={
                "error": {
                    "message": (
                        "This request requires more credits, or fewer "
                        f"max_tokens. You requested up to 2048 tokens, but "
                        f"can only afford {affordable}."
                    )
                }
            },
            request=request,
        )

    return handler


def test_over_budget_request_retries_at_the_affordable_ceiling(monkeypatch):
    seen: list[int] = []

    def handler(request):
        requested = json.loads(request.content)["max_tokens"]
        seen.append(requested)
        if requested > 853:
            return _payment_required(853)(request)
        return ok_response(request)

    respond(monkeypatch, handler)
    answer = build(max_output_tokens=2048).complete(system="s", prompt="p")

    assert answer == "Depth helps [E1]."
    # The first attempt asks for the configured ceiling; the retry asks for
    # exactly what the balance affords. Never more than two calls.
    assert seen == [2048, 853]


def test_retry_happens_once_and_a_second_402_is_surfaced(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        return _payment_required(853)(request)

    respond(monkeypatch, handler)
    with pytest.raises(LLMError) as excinfo:
        build(max_output_tokens=2048).complete(system="s", prompt="p")

    assert "402" in str(excinfo.value)
    assert len(calls) == 2


def test_budget_too_small_for_a_usable_answer_fails_loudly(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        return _payment_required(12)(request)

    respond(monkeypatch, handler)
    with pytest.raises(LLMError) as excinfo:
        build(max_output_tokens=2048).complete(system="s", prompt="p")

    # A 12-token completion is not an answer. Better a clear error than a
    # truncated one that looks grounded.
    assert "Top up" in str(excinfo.value)
    assert calls == [2048], "must not retry into a uselessly short answer"


def test_other_payment_errors_are_not_retried(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(
            402, json={"error": {"message": "Account suspended."}}, request=request
        )

    respond(monkeypatch, handler)
    with pytest.raises(LLMError, match="Account suspended"):
        build(max_output_tokens=2048).complete(system="s", prompt="p")

    assert calls == [2048], "no affordable ceiling to retry against"


# --- Provider selection ------------------------------------------------------
# OpenRouter running out of credits took down every AI feature, so the provider
# is now configurable. These tests prove the *selection* is right — that each
# endpoint gets its own base URL, key and headers — without calling any of them.


def test_gemini_uses_googles_openai_compatible_endpoint(monkeypatch):
    from app.core.config import get_settings
    from app.services.llm import PROVIDER_PROFILES, build_llm_provider

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-test-key", raising=False)
    monkeypatch.setattr(settings, "llm_base_url", "", raising=False)
    monkeypatch.setattr(settings, "llm_model", "", raising=False)
    # Blanked so this asserts the profile default rather than whatever the
    # developer happens to have pinned in their own backend/.env.
    monkeypatch.setattr(settings, "gemini_model", "", raising=False)
    build_llm_provider.cache_clear()

    provider = build_llm_provider()
    assert provider._base_url.endswith("/v1beta/openai")
    # The model name is asserted through the profile, not repeated here: it
    # has already moved once (2.5-flash stopped being served to new keys)
    # and this test is about the endpoint and headers.
    assert provider.name == PROVIDER_PROFILES["gemini"].default_model
    # Gemini 3 spends hidden thinking tokens out of the same max_tokens
    # budget as the answer, so the profile bounds it.
    assert provider._reasoning_effort == "low"
    assert provider.supports_images is True
    assert provider._headers()["Authorization"] == "Bearer gemini-test-key"
    # OpenRouter's attribution headers mean nothing to Google and are not sent.
    assert "HTTP-Referer" not in provider._headers()
    assert configured_llm_model() == PROVIDER_PROFILES["gemini"].default_model
    build_llm_provider.cache_clear()


def test_ollama_needs_no_api_key(monkeypatch):
    from app.core.config import get_settings
    from app.services.llm import build_llm_provider

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "ollama", raising=False)
    monkeypatch.setattr(settings, "llm_api_key", "", raising=False)
    monkeypatch.setattr(settings, "llm_base_url", "", raising=False)
    monkeypatch.setattr(settings, "llm_model", "", raising=False)
    build_llm_provider.cache_clear()

    assert build_llm_provider().name == "llama3.1:8b"
    build_llm_provider.cache_clear()


def test_an_unknown_provider_names_the_valid_ones(monkeypatch):
    from app.core.config import get_settings
    from app.services.llm import build_llm_provider

    monkeypatch.setattr(get_settings(), "llm_provider", "hal9000", raising=False)
    build_llm_provider.cache_clear()
    with pytest.raises(LLMConfigurationError) as excinfo:
        build_llm_provider()
    assert "gemini" in str(excinfo.value) and "openrouter" in str(excinfo.value)
    build_llm_provider.cache_clear()


def test_a_free_tier_quota_is_not_reported_as_an_empty_wallet(monkeypatch):
    """429 and 402 are different problems: one waits, the other needs money."""
    respond(
        monkeypatch,
        lambda request: httpx.Response(
            429,
            json={"error": {"message": "Quota exceeded for this model."}},
            headers={"retry-after": "37"},
            request=request,
        ),
    )
    with pytest.raises(LLMError) as excinfo:
        build().complete(system="s", prompt="p")
    message = str(excinfo.value)
    assert "quota is exhausted, not the account balance" in message
    assert "Retry after 37s" in message


def test_a_rejected_key_names_the_variable_to_fix(monkeypatch):
    respond(
        monkeypatch,
        lambda request: httpx.Response(
            401, json={"error": {"message": "Invalid API key"}}, request=request
        ),
    )
    with pytest.raises(LLMError) as excinfo:
        build().complete(system="s", prompt="p")
    assert "OPENROUTER_API_KEY" in str(excinfo.value)
