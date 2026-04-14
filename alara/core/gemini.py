"""Gemini API client for Alara."""

import logging
import tomllib
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from alara.security import vault

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alara.toml"
_MODEL = "gemini-2.5-flash"


def _load_config() -> dict:
    with _CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


class GeminiClient:
    """Thin wrapper around the google-genai SDK."""

    def __init__(self) -> None:
        api_key = vault.get_secret("gemini_api_key")
        if api_key is None:
            raise RuntimeError("Gemini API key not found. Run setup.")

        self._client = genai.Client(api_key=api_key)
        logger.debug("Gemini client initialised")

        config = _load_config()
        user = config.get("user", {})
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
            f"files, list directories, conduct research, and draft or edit written "
            f"content on the user's behalf. When the user asks you to perform one "
            f"of these actions, carry it out directly. Never tell the user you "
            f"cannot access their filesystem or perform local actions — those "
            f"capabilities exist and are handled by the system around you.\n"
            f"Prioritise accuracy, privacy, and helpfulness. Never fabricate facts."
        )
        logger.debug("System prompt built for user: %s", self._name)

    def chat(self, message: str, history: list[dict]) -> str:
        """Send a message with conversation history and return the text response.

        Args:
            message: The user's current message.
            history: List of prior turns as dicts with 'role' and 'content' keys.

        Returns:
            The assistant's response text.

        Raises:
            RuntimeError: On API errors with a descriptive message.
        """
        contents: list[genai_types.ContentUnion] = []

        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            # Gemini uses "model" for assistant turns
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

        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

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
            raise RuntimeError("Gemini returned an empty response.")
        return text
