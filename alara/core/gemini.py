"""Gemini API client for Alara — L1 with retry resilience and model fallback."""

import logging
import tomllib
from pathlib import Path

from google import genai
from google.genai import types as genai_types
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from alara.core.errors import AlaraAPIError
from alara.security import vault

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alara.toml"

_GEMINI_DEFAULTS: dict = {
    "primary_model": "gemini-2.5-flash",
    "fallback_model": "gemini-2.5-flash-lite",
    "request_timeout_seconds": 30,
    "max_retries": 4,
}


def _load_config() -> dict:
    with _CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient Gemini API errors that warrant a retry.

    Checks both google.api_core exception types (per spec) and the google-genai
    SDK's own ServerError class which wraps 5xx HTTP responses.
    """
    try:
        import google.api_core.exceptions as gac
        if isinstance(exc, (gac.ServiceUnavailable, gac.DeadlineExceeded)):
            return True
    except ImportError:
        pass

    try:
        from google.genai import errors as ge
        if isinstance(exc, ge.ServerError):
            return True
    except ImportError:
        pass

    return False


class GeminiClient:
    """Gemini API wrapper with retry resilience and automatic model fallback."""

    def __init__(self) -> None:
        api_key = vault.get_secret("gemini_api_key")
        if api_key is None:
            raise AlaraAPIError("Gemini API key not found. Run setup.")

        config = _load_config()
        user = config.get("user", {})
        gemini_cfg = {**_GEMINI_DEFAULTS, **config.get("gemini", {})}

        self._model: str = gemini_cfg["primary_model"]
        self._fallback_model: str = gemini_cfg["fallback_model"]
        self._max_retries: int = int(gemini_cfg["max_retries"])
        timeout_secs: float = float(gemini_cfg["request_timeout_seconds"])

        http_options = genai_types.HttpOptions(timeout=int(timeout_secs * 1000))
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        logger.debug(
            "Gemini client initialised — model=%s fallback=%s timeout=%ss retries=%d",
            self._model, self._fallback_model, timeout_secs, self._max_retries,
        )

        self._name: str = user.get("name", "User")
        self._timezone: str = user.get("timezone", "UTC")
        self._response_style: str = user.get("response_style", "concise")

        style_instruction = (
            "Keep responses concise and to the point."
            if self._response_style == "concise"
            else "Provide thorough, detailed responses."
        )

        self._system_prompt: str = (
            f"You are Alara, a secure personal AI assistant running locally on "
            f"{self._name}'s desktop.\n"
            f"Their local timezone is {self._timezone}.\n"
            f"Response style preference: {style_instruction}\n"
            f"You are an agent with real capabilities — you can read files, write "
            f"files, list directories, conduct research, draft or edit written "
            f"content, and manage email on the user's behalf. When the user asks "
            f"you to perform one of these actions, carry it out directly. Never "
            f"tell the user you cannot access their filesystem or perform local "
            f"actions — those capabilities exist and are handled by the system "
            f"around you.\n"
            f"Prioritise accuracy, privacy, and helpfulness. Never fabricate facts."
        )
        logger.debug("System prompt built for user: %s", self._name)

    def _call_api(self, message: str, history: list[dict], model: str) -> str:
        """Single raw API call to Gemini — no retry logic, no exception wrapping.

        Raises the original SDK exception on failure so tenacity can inspect it.
        """
        contents: list[genai_types.ContentUnion] = []

        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            gemini_role = "model" if role == "assistant" else "user"
            contents.append(
                genai_types.Content(
                    role=gemini_role,
                    parts=[genai_types.Part(text=content)],
                )
            )

        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=message)],
            )
        )

        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=self._system_prompt,
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        if usage:
            logger.debug(
                "Token usage — prompt: %s, candidates: %s, total: %s",
                getattr(usage, "prompt_token_count", "?"),
                getattr(usage, "candidates_token_count", "?"),
                getattr(usage, "total_token_count", "?"),
            )

        text = response.text
        if text is None:
            raise AlaraAPIError(f"Gemini ({model}) returned an empty response.")
        return text

    def chat(self, message: str, history: list[dict]) -> str:
        """Send a message with conversation history and return the text response.

        Retries up to max_retries times on transient errors with exponential
        backoff and jitter. If all retries on the primary model are exhausted,
        attempts the fallback model once. Raises AlaraAPIError on final failure.

        Args:
            message: The user's current message.
            history: Prior turns as dicts with 'role' and 'content' keys.

        Returns:
            The assistant's response text.

        Raises:
            AlaraAPIError: On non-retryable errors or total retry exhaustion.
        """
        # Build a tenacity-wrapped callable around the primary model call.
        # reraise=False means tenacity raises RetryError after exhaustion,
        # which we catch to attempt the fallback model.
        primary_with_retry = retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(initial=1, max=16),
            retry=retry_if_exception(_is_retryable),
            reraise=False,
        )(lambda: self._call_api(message, history, self._model))

        try:
            return primary_with_retry()

        except RetryError:
            logger.warning(
                "Primary model %s exhausted %d retries — attempting fallback %s",
                self._model, self._max_retries, self._fallback_model,
            )
            try:
                return self._call_api(message, history, self._fallback_model)
            except Exception as exc:
                raise AlaraAPIError(
                    f"Gemini unavailable — primary model {self._model} retried "
                    f"{self._max_retries} times and fallback {self._fallback_model} "
                    f"also failed: {exc}"
                ) from exc

        except Exception as exc:
            # Non-retryable error (4xx auth/bad-request, etc.)
            raise AlaraAPIError(f"Gemini API error: {exc}") from exc

    def append_system_prompt(self, fragment: str) -> None:
        """Append *fragment* to the existing system prompt.

        Called once at session startup to inject the Composio tool inventory
        so Gemini knows which external actions are available.

        Args:
            fragment: Plain-text block to append (e.g. from
                      MCPRegistry.get_system_prompt_fragment()).
        """
        if not fragment:
            return
        self._system_prompt = f"{self._system_prompt}\n\n{fragment}"
        logger.debug(
            "System prompt extended with %d-char tool fragment", len(fragment)
        )
