"""LLM access behind the LLMProvider interface (PRD Section 6).

OpenRouter is OpenAI-compatible, so this is one HTTP call rather than an SDK
dependency. Nothing outside this module knows which model answered — swapping
provider means writing another class with a `complete` method, not touching
answering logic.

The provider is deliberately thin. It sends a prompt and returns text; it does
no prompt construction, no citation parsing, and no grounding enforcement.
Those live in `answering.py`, so they stay under test without a network call and
apply identically whichever provider is configured.
"""

import base64
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


class OpenRouterProvider:
    """Implements the LLMProvider protocol against OpenRouter's chat API."""

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
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; "
                "add a key to .env or configure a different LLM_PROVIDER."
            )
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

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter's optional attribution headers.
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

    def _complete(self, *, messages: list[dict], max_output_tokens: int) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": max_output_tokens,
        }

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach the LLM provider: {exc}") from exc

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


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error or body)[:300]


@lru_cache
def build_llm_provider() -> OpenRouterProvider:
    """Build the configured provider. Raises LLMConfigurationError if unusable."""
    settings = get_settings()
    if settings.llm_provider != "openrouter":
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. "
            "Only 'openrouter' is implemented."
        )
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        timeout=settings.llm_timeout_seconds,
        app_title=settings.llm_app_title,
        app_url=settings.llm_app_url,
    )
