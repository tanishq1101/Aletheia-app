"""OpenAI-compatible provider tests.

The provider's own logic (headers, error surfacing, malformed responses) is
tested offline against a stubbed transport — those paths must be reliable
precisely when the network is not.

The real-provider tests are skipped unless the relevant key is configured, so
the suite stays runnable offline and free. They are *not* deleted: PRD Section 9
forbids claiming a provider works without running it, and they are the only
tests that prove a configured model actually exists and answers.
"""

import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.llm import (
    PROVIDER_PROFILES,
    LLMConfigurationError,
    LLMError,
    OpenAICompatibleProvider,
    build_llm_provider,
    configured_llm_model,
)


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    """`build_llm_provider` is lru_cached, so a stale instance would leak.

    Module-wide rather than per-test: any test that builds a provider from
    settings can otherwise hand the next one a client configured from the
    previous test's switches.
    """
    build_llm_provider.cache_clear()
    yield
    build_llm_provider.cache_clear()


def build(transport: httpx.MockTransport | None = None, **overrides):
    kwargs = {
        "api_key": "test-key",
        "model": "test/model",
        "base_url": "https://provider.test/v1",
        "temperature": 0.0,
        "max_output_tokens": 256,
        "timeout": 5.0,
    }
    kwargs.update(overrides)
    return OpenAICompatibleProvider(**kwargs)


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

    assert "OPENAI_API_KEY" in str(exc.value)


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
    # Only auth and content-type. Neither remaining provider wants vendor
    # attribution headers, and OpenAI rejects unknown ones outright.
    assert "x-title" not in captured["headers"]
    assert "http-referer" not in captured["headers"]
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
# These run against whichever provider is enabled in backend/.env, so the
# configuration that ships is the configuration that gets exercised. A key for
# a *disabled* provider does not enable them: that would test a path no request
# will ever take.


def _live_provider_ready() -> bool:
    settings = get_settings()
    active = settings.active_provider
    return bool(active and getattr(settings, f"{active}_api_key", ""))


live = pytest.mark.skipif(
    not _live_provider_ready(),
    reason=(
        "No enabled LLM provider with a key (check OPENAI_ENABLED / "
        "GEMINI_ENABLED in backend/.env) — live provider checks skipped."
    ),
)


@live
def test_live_model_answers_and_obeys_evidence_ids():
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
def test_live_model_declines_when_evidence_is_missing():
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
# Two providers, one switch each, exactly one enabled. These prove the
# *selection* is right — that the enabled endpoint gets its own base URL, key
# and model, and that a disabled one is genuinely never reached — without
# calling either of them.


def select(monkeypatch, *, openai: bool, gemini: bool):
    """Set the two switches and clear the provider cache.

    Both keys are set every time on purpose: the switch, not the presence of a
    key, has to be what decides. A test that proved selection by withholding a
    key would prove nothing about the switch.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_enabled", openai, raising=False)
    monkeypatch.setattr(settings, "gemini_enabled", gemini, raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-test-key", raising=False)
    # Blanked so these assert the profile defaults rather than whatever the
    # developer happens to have pinned in their own backend/.env.
    monkeypatch.setattr(settings, "openai_model", "", raising=False)
    monkeypatch.setattr(settings, "gemini_model", "", raising=False)
    build_llm_provider.cache_clear()
    return settings


def test_openai_enabled_alone_selects_openai(monkeypatch):
    select(monkeypatch, openai=True, gemini=False)

    provider = build_llm_provider()
    assert provider._base_url == "https://api.openai.com/v1"
    assert provider.name == PROVIDER_PROFILES["openai"].default_model
    assert provider._headers()["Authorization"] == "Bearer openai-test-key"
    # OpenAI rejects `reasoning_effort` on the models used here; only the
    # gemini profile sets it.
    assert provider._reasoning_effort is None
    assert configured_llm_model() == PROVIDER_PROFILES["openai"].default_model


def test_gemini_enabled_alone_selects_googles_openai_compatible_endpoint(monkeypatch):
    select(monkeypatch, openai=False, gemini=True)

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
    assert configured_llm_model() == PROVIDER_PROFILES["gemini"].default_model


def test_an_explicit_model_overrides_the_profile_default(monkeypatch):
    settings = select(monkeypatch, openai=True, gemini=False)
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1-mini", raising=False)
    build_llm_provider.cache_clear()

    assert build_llm_provider().name == "gpt-4.1-mini"
    assert configured_llm_model() == "gpt-4.1-mini"


def test_neither_enabled_is_a_configuration_error(monkeypatch):
    """Silently picking one would hide a deployment that configured nothing."""
    select(monkeypatch, openai=False, gemini=False)

    with pytest.raises(LLMConfigurationError) as excinfo:
        build_llm_provider()

    message = str(excinfo.value)
    assert "OPENAI_ENABLED" in message and "GEMINI_ENABLED" in message
    assert "both false" in message


def test_both_enabled_is_a_configuration_error(monkeypatch):
    """Two enabled providers is ambiguous about which account gets billed."""
    select(monkeypatch, openai=True, gemini=True)

    with pytest.raises(LLMConfigurationError) as excinfo:
        build_llm_provider()

    message = str(excinfo.value)
    assert "both true" in message
    assert "Exactly one" in message


def test_a_disabled_provider_is_never_called_when_the_enabled_one_fails(monkeypatch):
    """The regression guard for "off means off".

    This used to fall through to Gemini whenever its key was present, which
    made the switch a suggestion and billed an account the operator had
    deliberately turned off. The request must fail as OpenAI.
    """
    select(monkeypatch, openai=True, gemini=False)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            500, json={"error": {"message": "upstream exploded"}}, request=request
        )

    respond(monkeypatch, handler)

    with pytest.raises(LLMError) as excinfo:
        build_llm_provider().complete(system="rules", prompt="evidence")

    assert "upstream exploded" in str(excinfo.value)
    # One attempt, against OpenAI only. Google is never contacted, even
    # though GEMINI_API_KEY is set.
    assert len(calls) == 1
    assert "api.openai.com" in calls[0]
    assert not any("googleapis.com" in url for url in calls)


def test_a_missing_key_for_the_enabled_provider_is_not_covered_by_the_other(
    monkeypatch,
):
    """An OpenAI deployment with no OpenAI key is broken, not secretly Gemini."""
    settings = select(monkeypatch, openai=True, gemini=False)
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    build_llm_provider.cache_clear()

    with pytest.raises(LLMConfigurationError) as excinfo:
        build_llm_provider()

    assert "OPENAI_API_KEY" in str(excinfo.value)


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
    assert "OPENAI_API_KEY" in str(excinfo.value)


# --- max_tokens vs. max_completion_tokens ------------------------------------
# Newer reasoning-family models (o1/o3, some gpt-5 variants) reject the classic
# `max_tokens` field and ask for `max_completion_tokens` instead.


def test_max_tokens_rejection_retries_with_max_completion_tokens(monkeypatch):
    seen: list[tuple[str, int]] = []

    def handler(request):
        body = json.loads(request.content)
        if "max_tokens" in body:
            seen.append(("max_tokens", body["max_tokens"]))
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": (
                            "Unsupported parameter: 'max_tokens' is not "
                            "supported with this model. Use "
                            "'max_completion_tokens' instead."
                        )
                    }
                },
                request=request,
            )
        seen.append(("max_completion_tokens", body["max_completion_tokens"]))
        return ok_response(request)

    respond(monkeypatch, handler)
    answer = build().complete(system="s", prompt="p")

    assert answer == "Depth helps [E1]."
    # Retried exactly once, with the same ceiling under the new field name.
    assert seen == [("max_tokens", 256), ("max_completion_tokens", 256)]


def test_unrelated_400_is_not_retried(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(
            400,
            json={"error": {"message": "Invalid 'temperature': must be between 0 and 2."}},
            request=request,
        )

    respond(monkeypatch, handler)
    with pytest.raises(LLMError, match="temperature"):
        build().complete(system="s", prompt="p")

    assert len(calls) == 1, "no actionable hint, so no retry"


# --- Models that refuse a temperature ----------------------------------------
# Found live: gpt-5.6-luna answers only at its own default temperature and
# rejects LLM_TEMPERATURE=0.0 outright, which made every OpenAI request a 400.
# It went unnoticed because the old silent Gemini fallback answered instead.


def _temperature_refused(request):
    return httpx.Response(
        400,
        json={
            "error": {
                "message": (
                    "Unsupported value: 'temperature' does not support 0.0 "
                    "with this model. Only the default (1) value is supported."
                )
            }
        },
        request=request,
    )


def test_a_model_that_refuses_temperature_is_retried_without_it(monkeypatch):
    sent: list[dict] = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if "temperature" in body:
            return _temperature_refused(request)
        return ok_response(request)

    respond(monkeypatch, handler)

    assert build().complete(system="s", prompt="p") == "Depth helps [E1]."
    assert len(sent) == 2, "one rejected attempt, one retry"
    assert sent[0]["temperature"] == 0.0
    # Omitted entirely rather than sent as 1: the model's default is whatever
    # the model says it is, and this client should not have to know it.
    assert "temperature" not in sent[1]


def test_both_request_adaptations_compose(monkeypatch):
    """A model can need `max_completion_tokens` *and* no temperature.

    The previous one-shot retries could each fire once but never both, so a
    model in both families failed on the second 400 having already "used up"
    its retry.
    """
    sent: list[dict] = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if "max_tokens" in body:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": (
                            "Unsupported parameter: 'max_tokens' is not "
                            "supported with this model. Use "
                            "'max_completion_tokens' instead."
                        )
                    }
                },
                request=request,
            )
        if "temperature" in body:
            return _temperature_refused(request)
        return ok_response(request)

    respond(monkeypatch, handler)

    assert build().complete(system="s", prompt="p") == "Depth helps [E1]."
    assert len(sent) == 3
    assert sent[-1]["max_completion_tokens"] == 256
    assert "max_tokens" not in sent[-1]
    assert "temperature" not in sent[-1]


def test_an_unfixable_400_stops_instead_of_looping(monkeypatch):
    """Each adaptation applies once, so a provider that keeps refusing ends."""
    calls: list[dict] = []

    def handler(request):
        calls.append(json.loads(request.content))
        # Keeps asking for the same change even after it has been made.
        return _temperature_refused(request)

    respond(monkeypatch, handler)
    with pytest.raises(LLMError, match="400"):
        build().complete(system="s", prompt="p")

    assert len(calls) == 2, "one retry, then the error is surfaced"


# --- The negotiated request shape is learned once, not per call --------------
# Rediscovering it every time cost a 400 (and on gpt-5.6-luna a second 400)
# before every completion in the application — three round-trips where one
# would do, on every answer, agent step and extraction.


def _luna_like(seen: list[dict]):
    """A model that refuses `max_tokens` and then refuses any temperature."""

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "max_tokens" in body:
            return httpx.Response(400, json={"error": {"message":
                "Unsupported parameter: 'max_tokens' is not supported with "
                "this model. Use 'max_completion_tokens' instead."}},
                request=request)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message":
                "Unsupported value: 'temperature' does not support 0.0 with "
                "this model. Only the default (1) value is supported."}},
                request=request)
        return ok_response(request)

    return handler


def test_the_learned_request_shape_is_reused_on_later_calls(monkeypatch):
    seen: list[dict] = []
    respond(monkeypatch, _luna_like(seen))
    provider = build()

    assert provider.complete(system="s", prompt="one") == "Depth helps [E1]."
    assert len(seen) == 3, "first call pays to discover both adaptations"

    seen.clear()
    assert provider.complete(system="s", prompt="two") == "Depth helps [E1]."
    assert len(seen) == 1, "the model cannot change its mind; do not re-ask"
    assert "max_completion_tokens" in seen[0] and "temperature" not in seen[0]


def test_a_model_that_refuses_temperature_reports_itself_non_reproducible(monkeypatch):
    respond(monkeypatch, _luna_like([]))
    provider = build()
    assert provider.deterministic is True, "nothing refused yet"

    provider.complete(system="s", prompt="p")
    assert provider.deterministic is False, (
        "answering at the model's own sampling is not reproducible, and the "
        "reader of a cited claim is the one who needs to know that"
    )


def test_a_model_that_accepts_temperature_zero_stays_reproducible(monkeypatch):
    respond(monkeypatch, ok_response)
    provider = build()
    provider.complete(system="s", prompt="p")
    assert provider.deterministic is True


def test_a_rejected_reasoning_effort_is_dropped_rather_than_failing(monkeypatch):
    seen: list[dict] = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(400, json={"error": {"message":
                "Unsupported value: 'reasoning_effort' does not support "
                "'minimal' with this model. Supported values are: 'none'"}},
                request=request)
        return ok_response(request)

    respond(monkeypatch, handler)
    assert build(reasoning_effort="minimal").complete(system="s", prompt="p")
    assert len(seen) == 2 and "reasoning_effort" not in seen[-1]


def test_a_budget_retry_keeps_the_shape_the_model_already_demanded(monkeypatch):
    """A 402 retry that reverts to rejected fields turns 'top up' into a 400."""
    seen: list[dict] = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "max_tokens" in body:
            return httpx.Response(400, json={"error": {"message":
                "Use 'max_completion_tokens' instead."}}, request=request)
        if body["max_completion_tokens"] > 300:
            return httpx.Response(402, json={"error": {"message":
                "Requires more credits: can only afford 300"}}, request=request)
        return ok_response(request)

    respond(monkeypatch, handler)
    assert build(max_output_tokens=2048).complete(system="s", prompt="p")
    assert "max_completion_tokens" in seen[-1] and "max_tokens" not in seen[-1]
    assert seen[-1]["max_completion_tokens"] == 300


# --- Empty completions -------------------------------------------------------
# Two causes needing opposite responses. Both were fatal before, and both made
# the research agent's combined report fail — the visible symptom that started
# this work.


def _empty(finish_reason: str, request, reasoning: int = 0):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": ""}, "finish_reason": finish_reason}],
        "usage": {"completion_tokens_details": {"reasoning_tokens": reasoning}},
    }, request=request)


def test_a_transient_empty_completion_is_retried_at_the_same_budget(monkeypatch):
    seen: list[int] = []

    def handler(request):
        budget = json.loads(request.content)["max_tokens"]
        seen.append(budget)
        return _empty("stop", request) if len(seen) == 1 else ok_response(request)

    respond(monkeypatch, handler)
    assert build().complete(system="s", prompt="p") == "Depth helps [E1]."
    assert seen == [256, 256], "nothing suggests the budget was the problem"


def test_a_budget_starved_empty_completion_is_retried_with_more_room(monkeypatch):
    """Measured on gpt-5.6-luna: 2048 went entirely to reasoning and returned
    nothing, while 8192 reasoned briefly and wrote a full answer. Retrying the
    same ceiling would have failed identically every time."""
    seen: list[int] = []

    def handler(request):
        budget = json.loads(request.content)["max_tokens"]
        seen.append(budget)
        return (_empty("length", request, reasoning=budget)
                if len(seen) == 1 else ok_response(request))

    respond(monkeypatch, handler)
    assert build(max_output_tokens=2048).complete(system="s", prompt="p")
    assert seen == [2048, 8192], "raised, not repeated"


def test_a_second_empty_completion_is_surfaced_rather_than_looped(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return _empty("stop", request)

    respond(monkeypatch, handler)
    with pytest.raises(LLMError, match="empty completion"):
        build().complete(system="s", prompt="p")

    assert len(calls) == 2, "retried once, not until it works"


def test_starvation_at_the_ceiling_says_which_setting_to_raise(monkeypatch):
    """No larger budget is available, so an identical retry would only waste
    a request. Name the setting instead."""
    respond(monkeypatch, lambda request: _empty("length", request, reasoning=99))

    with pytest.raises(LLMError, match="LLM_MAX_OUTPUT_TOKENS_CEILING"):
        build(max_output_tokens=get_settings().llm_max_output_tokens_ceiling).complete(
            system="s", prompt="p"
        )


def test_a_caller_can_ask_for_more_room_than_the_configured_default(monkeypatch):
    """A combined report is structurally longer than one answer."""
    seen: list[int] = []

    def handler(request):
        seen.append(json.loads(request.content)["max_tokens"])
        return ok_response(request)

    respond(monkeypatch, handler)
    build(max_output_tokens=256).complete(system="s", prompt="p", max_output_tokens=4096)
    assert seen == [4096]
