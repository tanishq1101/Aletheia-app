"""LLM access behind the LLMProvider interface (PRD Section 6).

Both providers used here speak the OpenAI chat-completions shape, so this is
one HTTP call rather than an SDK dependency per vendor. Nothing outside this
module knows which model answered — swapping provider is an env var, not a
change to answering logic.

Two endpoints are supported, each with its own switch in `.env`:

    OPENAI_ENABLED=true    OpenAI
    GEMINI_ENABLED=true    Google's OpenAI-compatible endpoint

Exactly one may be enabled. A disabled provider is never called — not as a
standby, not on failure, not when the other one's key is missing. That is the
point of the switch: "off" has to mean off, or an operator cannot tell which
account a request was actually billed to. Zero or two enabled is a
configuration error that says which mistake was made.

The provider is deliberately thin. It sends a prompt and returns text; it does
no prompt construction, no citation parsing, and no grounding enforcement.
Those live in `answering.py`, so they stay under test without a network call and
apply identically whichever provider is configured.
"""

import base64
from dataclasses import dataclass
import re
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable.

    Always surfaced to the caller as a real reason. An answering path that
    swallowed this would return an ungrounded or empty answer that looks
    indistinguishable from a real one.
    """


class LLMConfigurationError(LLMError):
    """The provider is not configured — a deployment problem, not a model one."""


class EmptyCompletionError(LLMError):
    """The model returned a successful response containing no text.

    Its own subclass only so `_complete` can retry precisely this and nothing
    else. It stays an `LLMError`, so a caller that does not care still sees a
    real failure rather than an empty answer.

    `finish_reason` distinguishes the two ways this happens, which need
    opposite responses — see `_complete`.
    """

    def __init__(self, message: str, *, finish_reason: str | None = None):
        super().__init__(message)
        self.finish_reason = finish_reason


class CompletionText(str):
    """String-compatible completion carrying an explicit output-limit flag."""
    def __new__(cls, value: str, *, truncated: bool = False):
        result = super().__new__(cls, value)
        result.truncated = truncated
        return result


class OpenAICompatibleProvider:
    """Implements the LLMProvider protocol against any OpenAI-shaped chat API.

    `label` and `key_env` exist only so a failure names the account the operator
    actually has to go and fix. A message that says "out of credits" without
    saying *whose* credits is a support ticket, not an error.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
        label: str = "OpenAI",
        key_env: str = "OPENAI_API_KEY",
        credits_url: str = "https://platform.openai.com/settings/organization/billing/overview",
        supports_images: bool = True,
        reasoning_effort: str | None = None,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                f"{key_env} is not set, but that provider is the enabled one. "
                "Grounded answering needs an LLM: add the key to backend/.env, "
                "or enable the other provider instead."
            )
        self._label = label
        self._key_env = key_env
        self._credits_url = credits_url
        self._supports_images = supports_images
        self._reasoning_effort = reasoning_effort
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        # What this model has already told us it accepts. Learned from its own
        # 400s on the first call and kept for the life of the provider: the
        # answer cannot change under a fixed model name, so re-discovering it
        # on every call costs two wasted round-trips per answer and nothing
        # else. See `_complete`.
        self._shape = dict(_DEFAULT_REQUEST_SHAPE)

    @property
    def name(self) -> str:
        return self._model

    @property
    def supports_images(self) -> bool:
        return self._supports_images

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @property
    def deterministic(self) -> bool:
        """Whether repeating a question can be expected to repeat its answer.

        False once the model has refused `temperature`, because it then answers
        at its own default sampling. Exposed rather than only logged: an
        evidence tool that cannot promise a re-runnable answer has to say so on
        the answer itself, not in a server log nobody reading the answer sees.
        """
        return self._shape["send_temperature"] and self._temperature == 0.0

    def complete(
        self, *, system: str, prompt: str, max_output_tokens: int | None = None
    ) -> str:
        """One completion. `max_output_tokens` overrides the configured ceiling.

        The override exists for callers whose output is structurally larger
        than a single answer — a combined report over a dozen evidence blocks
        needs room the per-answer budget was never sized for.
        """
        return self._complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_output_tokens=max_output_tokens or self._max_output_tokens,
        )

    def complete_with_image(
        self,
        *,
        system: str,
        prompt: str,
        image: bytes,
        media_type: str,
        max_output_tokens: int,
    ) -> str:
        """One bounded vision completion; image bytes never leave this provider seam."""
        encoded = base64.b64encode(image).decode("ascii")
        return self._complete(
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{encoded}"
                            },
                        },
                    ],
                },
            ],
            max_output_tokens=min(max_output_tokens, self._max_output_tokens),
        )

    def _post(
        self,
        *,
        messages: list[dict],
        max_output_tokens: int,
        token_param: str = "max_tokens",
        send_temperature: bool = True,
        send_reasoning_effort: bool = True,
    ) -> httpx.Response:
        payload = {
            "model": self._model,
            "messages": messages,
            token_param: max_output_tokens,
        }
        if send_temperature:
            payload["temperature"] = self._temperature
        if send_reasoning_effort and self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        try:
            return httpx.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach the LLM provider: {exc}") from exc

    def _complete(self, *, messages: list[dict], max_output_tokens: int) -> str:
        """One completion, retrying once if the model returns nothing at all.

        An empty completion has two causes that need opposite responses, and
        the model says which in `finish_reason`:

        `"length"` — the output budget was consumed before a single visible
        token was written. On a reasoning model the budget covers hidden
        reasoning *and* the answer, and the split is not proportional: measured
        on gpt-5.6-luna, a ceiling of 2048 or 4000 went entirely to reasoning
        and returned nothing, while 8192 reasoned for 69 tokens and wrote 6559.
        Below some floor these models produce no answer at all, and retrying
        the same ceiling would fail identically every time. So the ceiling is
        raised instead — read off the model's own report rather than a table of
        which models reason, so a future model needs no change here.

        Anything else — typically `"stop"` with empty content — is transient,
        and the same request succeeds on the next attempt. That is a property
        of answering at the model's own default sampling, which is what every
        model refusing `temperature=0` forces (see `deterministic`).

        Either way it is retried exactly once. Once, not until it works: a
        second empty completion is a real symptom and has to reach the caller
        as one, rather than being hidden behind a loop that turns a broken
        model into a slow one.
        """
        try:
            return self._attempt(
                messages=messages, max_output_tokens=max_output_tokens
            )
        except EmptyCompletionError as exc:
            retry_tokens = max_output_tokens
            if exc.finish_reason == "length":
                retry_tokens = min(
                    max_output_tokens * _OUTPUT_ESCALATION,
                    get_settings().llm_max_output_tokens_ceiling,
                )
                if retry_tokens <= max_output_tokens:
                    # Already at the ceiling: raising it is not available, so
                    # say that rather than burning an identical retry.
                    raise LLMError(
                        f"{exc} The output ceiling is already at the "
                        f"configured maximum of {max_output_tokens} tokens, so "
                        "there is no larger budget to retry with. Raise "
                        "LLM_MAX_OUTPUT_TOKENS_CEILING in backend/.env."
                    ) from exc
                log.warning(
                    "%s spent its entire %s-token output budget on reasoning "
                    "for %s without writing an answer; retrying once at %s.",
                    self._label, max_output_tokens, self._model, retry_tokens,
                )
            else:
                log.warning(
                    "%s returned an empty completion for %s (finish_reason "
                    "%r); retrying once.",
                    self._label, self._model, exc.finish_reason,
                )
        return self._attempt(
            messages=messages, max_output_tokens=retry_tokens
        )

    def _attempt(self, *, messages: list[dict], max_output_tokens: int) -> str:
        # Newer models reject request fields that older ones require: the
        # gpt-5 family wants `max_completion_tokens` rather than `max_tokens`,
        # and several refuse any `temperature` but their own default. Both are
        # read off the provider's own 400 rather than a hardcoded model list,
        # so a new model in either family needs no code change here — and a
        # model needing *both* gets both, which one-shot retries did not.
        #
        # Each adaptation applies at most once, so the loop terminates: every
        # pass either changes the request in a way it cannot change again, or
        # stops. The negotiated result is remembered on the provider
        # (`self._shape`) rather than rediscovered per call: a fixed model name
        # cannot change its mind about which fields it accepts, so re-learning
        # it every time bought nothing and cost two rejected round-trips before
        # every single completion in the application.
        response = self._post(
            messages=messages, max_output_tokens=max_output_tokens, **self._shape
        )
        while response.status_code == 400:
            adaptation = _adaptation_for(_error_detail(response), self._shape)
            if adaptation is None:
                break
            for field in adaptation:
                log.warning(
                    "%s rejected the request for %s; %s",
                    self._label,
                    self._model,
                    _ADAPTATION_NOTES[field],
                )
            self._shape.update(adaptation)
            response = self._post(
                messages=messages, max_output_tokens=max_output_tokens, **self._shape
            )

        # `max_tokens` is a reservation, not a spend: a provider refuses the
        # whole request when the remaining balance cannot cover the ceiling,
        # even though the answer itself would cost a fraction of it. When the
        # refusal states an affordable ceiling, retry once against it so a low
        # balance shortens an answer instead of removing every AI feature.
        # Only this one condition retries — every other non-200 fails at once.
        if response.status_code == 402:
            detail = _error_detail(response)
            affordable = _affordable_tokens(detail)
            if affordable is not None and affordable < max_output_tokens:
                if affordable < MIN_USABLE_OUTPUT_TOKENS:
                    raise LLMError(
                        f"LLM provider returned 402: {detail} "
                        f"The remaining balance affords {affordable} output "
                        f"tokens, below the {MIN_USABLE_OUTPUT_TOKENS} needed "
                        "for a usable grounded answer. Top up the account."
                    )
                log.warning(
                    "LLM budget below requested ceiling — retrying with "
                    "max_tokens=%s instead of %s. Answers may be shorter.",
                    affordable,
                    max_output_tokens,
                )
                response = self._post(
                    messages=messages,
                    max_output_tokens=affordable,
                    # Without the learned shape this retry reverts to the
                    # defaults the model already rejected, turning a solvable
                    # budget problem into an unrelated 400.
                    **self._shape,
                )

        if response.status_code == 402:
            # By far the most common way this deployment breaks, and the raw
            # provider text ("Prompt tokens limit exceeded: 3562 > 2642") reads
            # as a bug in the app rather than an empty wallet. Name the cause
            # first, keep the provider's words after it.
            raise LLMError(
                f"The {self._label} account is out of credits, so no answer "
                "could be generated. Everything else — search, reranking, "
                "extraction — runs locally and is unaffected. Top up at "
                f"{self._credits_url}, or enable the other provider in "
                "backend/.env (see .env.example). "
                f"Provider said (402): {_error_detail(response)}"
            )

        if response.status_code == 429:
            # The way a free tier actually fails. Distinguish it from an empty
            # wallet so the operator waits rather than reaching for a card.
            retry_after = response.headers.get("retry-after")
            wait = f" Retry after {retry_after}s." if retry_after else ""
            raise LLMError(
                f"{self._label} refused the request: the model's rate or daily "
                f"quota is exhausted, not the account balance.{wait} "
                f"Provider said (429): {_error_detail(response)}"
            )

        if response.status_code in (401, 403):
            raise LLMError(
                f"{self._label} rejected the credentials in {self._key_env} "
                f"({response.status_code}). Check the key is current and has "
                f"access to {self._model!r}. "
                f"Provider said: {_error_detail(response)}"
            )

        if response.status_code != 200:
            # Include the provider's own message — "LLM call failed" alone is
            # not diagnosable, and PRD Section 9 forbids swallowing the reason.
            raise LLMError(
                f"LLM provider returned {response.status_code}: "
                f"{_error_detail(response)}"
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"LLM provider returned an unreadable response: {exc}"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            finish_reason = body["choices"][0].get("finish_reason")
            reasoning_tokens = (
                (body.get("usage") or {}).get("completion_tokens_details") or {}
            ).get("reasoning_tokens")
            raise EmptyCompletionError(
                f"{self._label} returned an empty completion for "
                f"{self._model} (finish_reason: {finish_reason!r}, "
                f"reasoning tokens: {reasoning_tokens}). The request was "
                "accepted and billed, so this is the model spending its output "
                "budget without writing an answer — not a credentials, quota "
                "or prompt problem.",
                finish_reason=finish_reason,
            )

        usage = body.get("usage") or {}
        log.info(
            "LLM %s answered — %s prompt / %s completion tokens",
            self._model,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )
        return CompletionText(content.strip(), truncated=body["choices"][0].get("finish_reason") == "length")


# The request fields a model may refuse, and what this client sends by default.
_DEFAULT_REQUEST_SHAPE = {
    "token_param": "max_tokens",
    "send_temperature": True,
    "send_reasoning_effort": True,
}

#: What each retry actually costs, for the log. Dropping the temperature is the
#: one that matters: LLM_TEMPERATURE=0.0 is what makes an answer re-verifiable,
#: and a model that refuses it answers at its own default instead. That is a
#: real change in behaviour and has to be visible, not silently absorbed.
_ADAPTATION_NOTES = {
    "token_param": "retrying with max_completion_tokens instead of max_tokens.",
    "send_reasoning_effort": (
        "this model does not accept the configured reasoning_effort. Retrying "
        "without it — the model will use its own default effort."
    ),
    "send_temperature": (
        "this model does not accept a temperature. Retrying without it — "
        "answers will use the model's own default and are no longer "
        "deterministic, so repeating a question may not repeat its answer."
    ),
}


def _adaptation_for(detail: str, shape: dict) -> dict | None:
    """What a 400 is asking the caller to change, or None if it is not.

    Keyed off the provider's own words so the rule is "believe the error",
    not "remember which models are in which family". `shape` is what has
    already been tried, so an adaptation is never offered twice.
    """
    lowered = detail.lower()

    if "max_completion_tokens" in lowered and shape["token_param"] == "max_tokens":
        return {"token_param": "max_completion_tokens"}

    # e.g. "Unsupported value: 'temperature' does not support 0.0 with this
    # model. Only the default (1) value is supported." Omitting the field
    # accepts the model's default, which costs determinism — see the warning
    # logged in `_complete` — but is the only way these models answer at all.
    refuses_temperature = "temperature" in lowered and any(
        phrase in lowered
        for phrase in ("unsupported", "does not support", "not supported")
    )
    if refuses_temperature and shape["send_temperature"]:
        return {"send_temperature": False}

    # A provider that accepts `reasoning_effort` may still refuse the specific
    # level configured for it (gpt-5.6-luna rejects "minimal" while accepting
    # "none", "low", "medium" and "high"). Dropping the field is always valid —
    # it means "use your default" — so this never needs a per-model level table.
    refuses_reasoning_effort = "reasoning_effort" in lowered and any(
        phrase in lowered
        for phrase in ("unsupported", "does not support", "not supported")
    )
    if refuses_reasoning_effort and shape["send_reasoning_effort"]:
        return {"send_reasoning_effort": False}

    return None


# A provider refusing an over-budget request states, in prose, the largest
# `max_tokens` the remaining balance affords. That number is the only
# machine-actionable part of the message, so it is parsed rather than guessed.
_AFFORDABLE_TOKENS = re.compile(r"can only afford (\d+)", re.IGNORECASE)

# Below this a completion is too short to be a usable grounded answer, so a
# retry would trade a clear error for a truncated one. Fail loudly instead.
MIN_USABLE_OUTPUT_TOKENS = 256

#: How much to raise the output ceiling when a model spends the whole budget
#: reasoning and writes nothing. Four, because the gap measured on gpt-5.6-luna
#: between "returns nothing" (2048) and "reasons briefly then answers in full"
#: (8192) is exactly that, and a smaller step would just buy a second failure.
_OUTPUT_ESCALATION = 4


def _affordable_tokens(detail: str) -> int | None:
    match = _AFFORDABLE_TOKENS.search(detail)
    return int(match.group(1)) if match else None


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    # Most providers return a dict with an "error" key; Google's OpenAI-compat
    # surface wraps that same shape in a list instead.
    if isinstance(body, list):
        body = body[0] if body else {}
    if not isinstance(body, dict):
        return str(body)[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error or body)[:300]


@dataclass(frozen=True)
class ProviderProfile:
    """What differs between endpoints that both speak OpenAI chat-completions."""

    label: str
    key_env: str
    #: Which `Settings` field holds this provider's model override. Blank there
    #: means "use `default_model`", so the name is written down once.
    model_setting: str
    default_base_url: str
    default_model: str
    credits_url: str
    #: Gemini 3 models spend hidden "thinking" tokens out of the same
    #: max_tokens budget as the visible answer. On a small, bounded budget
    #: (figure interpretation) that thinking can consume nearly all of it,
    #: leaving a truncated one-line completion. "low" leaves enough thinking
    #: to stay accurate while giving the visible answer room to breathe.
    #: None omits the field entirely for providers that reject unknown ones.
    reasoning_effort: str | None = None


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        model_setting="openai_model",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.6-luna",
        credits_url="https://platform.openai.com/settings/organization/billing/overview",
    ),
    # Google exposes an OpenAI-compatible surface, so the same client works.
    # The free tier is a real one: no card, and it does vision, which the
    # figure-interpretation path needs.
    "gemini": ProviderProfile(
        label="Google Gemini",
        key_env="GEMINI_API_KEY",
        model_setting="gemini_model",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        # gemini-2.5-flash is no longer available to new API keys as of this
        # writing (Google's API returns a 404 telling callers to switch to
        # gemini-3.6-flash) — verified directly against the API.
        default_model="gemini-3.6-flash",
        credits_url="https://aistudio.google.com/apikey",
        reasoning_effort="low",
    ),
}

# Both keys live in .env at once, so the switches — not the presence of a key —
# decide who answers. Named here so the two error messages below and the
# .env sections stay spelled the same way.
_ENABLE_FLAGS = "OPENAI_ENABLED and GEMINI_ENABLED"


def _selected_provider(settings) -> str:
    """The one enabled provider, or a configuration error naming the mistake."""
    enabled = settings.enabled_providers
    if len(enabled) == 1:
        return enabled[0]
    if not enabled:
        raise LLMConfigurationError(
            f"No LLM provider is enabled: {_ENABLE_FLAGS} are both false. "
            "Grounded answering needs one — set exactly one of them to true "
            "in backend/.env. Search, reranking and extraction run locally "
            "and are unaffected."
        )
    raise LLMConfigurationError(
        f"{_ENABLE_FLAGS} are both true, so which account should be billed "
        "for an answer is ambiguous. Exactly one may be enabled — set the "
        "other to false in backend/.env."
    )


def _provider_model(settings, provider_name: str) -> str:
    """The configured model for a provider, falling back to its profile default."""
    profile = PROVIDER_PROFILES[provider_name]
    override = getattr(settings, profile.model_setting, "") or ""
    return override.strip() or profile.default_model


def _build_provider(settings, provider_name: str) -> OpenAICompatibleProvider:
    profile = PROVIDER_PROFILES[provider_name]
    api_key = getattr(settings, f"{provider_name}_api_key")
    return OpenAICompatibleProvider(
        api_key=api_key,
        model=_provider_model(settings, provider_name),
        base_url=profile.default_base_url,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout=settings.llm_timeout_seconds,
        label=profile.label,
        key_env=profile.key_env,
        credits_url=profile.credits_url,
        reasoning_effort=profile.reasoning_effort,
    )


@lru_cache
def build_llm_provider() -> OpenAICompatibleProvider:
    """Build the enabled provider. Raises LLMConfigurationError if unusable.

    There is deliberately no failover. A disabled provider is not a standby:
    silently answering from the other account would make the switch a
    suggestion, and would hide which vendor actually saw the evidence.
    """
    settings = get_settings()
    return _build_provider(settings, _selected_provider(settings))


def configured_llm_model() -> str:
    """Return the selected model name without constructing a network client."""
    settings = get_settings()
    return _provider_model(settings, _selected_provider(settings))
