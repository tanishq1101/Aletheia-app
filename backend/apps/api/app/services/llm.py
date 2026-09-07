"""LLM access behind the LLMProvider interface (PRD Section 6).

Every provider used here speaks the OpenAI chat-completions shape, so this is
one HTTP call rather than an SDK dependency per vendor. Nothing outside this
module knows which model answered — swapping provider is an env var, not a
change to answering logic.

`LLM_PROVIDER` selects the endpoint: `openrouter`, `gemini` (Google's
OpenAI-compatible endpoint, which has a genuinely free tier and does vision),
`groq`, `ollama` for a local model, or `custom` with an explicit base URL.
Vendor-specific behaviour is kept to two things — the attribution headers
OpenRouter accepts, and its habit of quoting an affordable `max_tokens` in a
402 — so adding a fifth endpoint stays a config entry.

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
        app_title: str = "",
        app_url: str = "",
        label: str = "OpenRouter",
        key_env: str = "OPENROUTER_API_KEY",
        credits_url: str = "https://openrouter.ai/settings/credits",
        send_attribution_headers: bool = True,
        requires_api_key: bool = True,
        supports_images: bool = True,
    ) -> None:
        if not api_key and requires_api_key:
            raise LLMConfigurationError(
                f"{key_env} is not set. Grounded answering needs an LLM; "
                "add a key to .env or configure a different LLM_PROVIDER."
            )
        self._label = label
        self._key_env = key_env
        self._credits_url = credits_url
        self._send_attribution_headers = send_attribution_headers
        self._supports_images = supports_images
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        self._app_title = app_title
        self._app_url = app_url

    @property
    def name(self) -> str:
        return self._model

    @property
    def supports_images(self) -> bool:
        return self._supports_images

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter's optional attribution headers. Other endpoints reject
        # or ignore unknown headers, so they are only sent where they mean
        # something.
        if self._send_attribution_headers:
            if self._app_url:
                headers["HTTP-Referer"] = self._app_url
            if self._app_title:
                headers["X-Title"] = self._app_title
        return headers

    def complete(self, *, system: str, prompt: str) -> str:
        return self._complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_output_tokens=self._max_output_tokens,
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

    def _post(self, *, messages: list[dict], max_output_tokens: int) -> httpx.Response:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": max_output_tokens,
        }
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
        response = self._post(messages=messages, max_output_tokens=max_output_tokens)

        # `max_tokens` is a reservation, not a spend: the provider refuses the
        # whole request when the remaining balance cannot cover the ceiling,
        # even though the answer itself would cost a fraction of it. Retry once
        # against the stated affordable ceiling so a low balance shortens an
        # answer instead of removing every AI feature. Only this one condition
        # retries — every other non-200 still fails immediately.
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
                    messages=messages, max_output_tokens=affordable
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
                f"{self._credits_url}, or switch LLM_PROVIDER to a free "
                "endpoint (see .env.example). "
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
            raise LLMError("LLM provider returned an empty completion.")

        usage = body.get("usage") or {}
        log.info(
            "LLM %s answered — %s prompt / %s completion tokens",
            self._model,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )
        return CompletionText(content.strip(), truncated=body["choices"][0].get("finish_reason") == "length")


# OpenRouter answers an over-budget request with 402 and states, in prose, the
# largest `max_tokens` the remaining balance affords. That number is the only
# machine-actionable part of the message, so it is parsed rather than guessed.
_AFFORDABLE_TOKENS = re.compile(r"can only afford (\d+)", re.IGNORECASE)

# Below this a completion is too short to be a usable grounded answer, so a
# retry would trade a clear error for a truncated one. Fail loudly instead.
MIN_USABLE_OUTPUT_TOKENS = 256


def _affordable_tokens(detail: str) -> int | None:
    match = _AFFORDABLE_TOKENS.search(detail)
    return int(match.group(1)) if match else None


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error or body)[:300]


# Backwards-compatible name. The class stopped being OpenRouter-specific when
# a second endpoint was added; the old name is kept so existing imports and
# tests continue to mean what they meant.
OpenRouterProvider = OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderProfile:
    """What differs between endpoints that all speak OpenAI chat-completions."""

    label: str
    key_env: str
    default_base_url: str
    default_model: str
    credits_url: str
    attribution_headers: bool = False
    requires_api_key: bool = True
    #: Vision is not universal, and figure interpretation silently degrades to
    #: a confident guess without it. Recorded so callers can check rather than
    #: discover it from a bad answer.
    supports_images: bool = True


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openrouter": ProviderProfile(
        label="OpenRouter",
        key_env="OPENROUTER_API_KEY",
        default_base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-haiku-4.5",
        credits_url="https://openrouter.ai/settings/credits",
        attribution_headers=True,
    ),
    # Google exposes an OpenAI-compatible surface, so the same client works.
    # The free tier is a real one: no card, and it does vision, which the
    # figure-interpretation path needs.
    "gemini": ProviderProfile(
        label="Google Gemini",
        key_env="GEMINI_API_KEY",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        credits_url="https://aistudio.google.com/apikey",
    ),
    # Fast and free, but text-only here: figure interpretation will fail
    # loudly rather than answer from the caption alone.
    "groq": ProviderProfile(
        label="Groq",
        key_env="GROQ_API_KEY",
        default_base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        credits_url="https://console.groq.com/keys",
        supports_images=False,
    ),
    # Local models. No key, no quota, no network egress.
    "ollama": ProviderProfile(
        label="Ollama",
        key_env="LLM_API_KEY",
        default_base_url="http://localhost:11434/v1",
        default_model="llama3.1:8b",
        credits_url="https://ollama.com/download",
        requires_api_key=False,
        supports_images=False,
    ),
    # Anything else OpenAI-shaped; base URL and model must be given explicitly.
    "custom": ProviderProfile(
        label="the configured LLM endpoint",
        key_env="LLM_API_KEY",
        default_base_url="",
        default_model="",
        credits_url="the provider's console",
    ),
}


@lru_cache
def build_llm_provider() -> OpenAICompatibleProvider:
    """Build the configured provider. Raises LLMConfigurationError if unusable."""
    settings = get_settings()
    profile = PROVIDER_PROFILES.get(settings.llm_provider)
    if profile is None:
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. "
            f"Choose one of: {', '.join(sorted(PROVIDER_PROFILES))}."
        )

    # OpenRouter keeps its own settings so existing deployments are untouched.
    if settings.llm_provider == "openrouter":
        api_key = settings.openrouter_api_key
        base_url = settings.openrouter_base_url
        model = settings.openrouter_model
    elif settings.llm_provider == "gemini":
        api_key = settings.gemini_api_key
        base_url = settings.llm_base_url or profile.default_base_url
        model = settings.llm_model or profile.default_model
    else:
        api_key = settings.llm_api_key
        base_url = settings.llm_base_url or profile.default_base_url
        model = settings.llm_model or profile.default_model

    if not base_url or not model:
        raise LLMConfigurationError(
            f"LLM_PROVIDER={settings.llm_provider!r} needs both LLM_BASE_URL "
            "and LLM_MODEL set; it has no defaults to fall back on."
        )

    return OpenAICompatibleProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout=settings.llm_timeout_seconds,
        app_title=settings.llm_app_title,
        app_url=settings.llm_app_url,
        label=profile.label,
        key_env=profile.key_env,
        credits_url=profile.credits_url,
        send_attribution_headers=profile.attribution_headers,
        requires_api_key=profile.requires_api_key,
        supports_images=profile.supports_images,
    )


def configured_llm_model() -> str:
    """Return the selected model name without constructing a network client."""
    settings = get_settings()
    profile = PROVIDER_PROFILES.get(settings.llm_provider)
    if profile is None:
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. "
            f"Choose one of: {', '.join(sorted(PROVIDER_PROFILES))}."
        )
    if settings.llm_provider == "openrouter":
        return settings.openrouter_model
    return settings.llm_model or profile.default_model
