"""Intent classification for user messages."""

import json
import logging
import re

from alara.core.gemini import GeminiClient

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset(
    {
        "research",
        "file_read",
        "file_write",
        "file_list",
        "write_draft",
        "write_edit",
        "chat",
        "unknown",
    }
)

_CLASSIFICATION_PROMPT = """\
You are an intent classifier for a personal desktop AI assistant called Alara.

Classify the following user message into exactly one of these intents:
- research       : user wants information, an explanation, or a knowledge-based answer
- file_read      : user wants to read or view the contents of a file
- file_write     : user wants to create, write, or save a file
- file_list      : user wants to list files or directories
- write_draft    : user wants a new piece of writing generated (email, essay, code, etc.)
- write_edit     : user wants to edit or improve existing text
- chat           : general conversation, greetings, questions about Alara, small talk
- unknown        : cannot be classified into any of the above

Respond with ONLY a JSON object in this exact format (no markdown fences, no extra text):
{{"intent": "<intent>", "params": {{}}}}

Optionally populate "params" with relevant extracted values such as:
- "path" for file intents
- "query" for research
- "prompt" for write_draft
- "original" and "instructions" for write_edit

User message: {message}
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    return text.strip()


def _is_transient(exc: Exception) -> bool:
    """Return True for errors that are worth retrying (rate limit, unavailable)."""
    msg = str(exc).upper()
    return any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))


def parse_intent(message: str, client: GeminiClient) -> dict:
    """Classify *message* into a structured intent dict.

    Retries once on transient API errors before falling back.

    Returns:
        A dict with keys "intent" (str) and "params" (dict).
        Falls back to {"intent": "chat", "params": {}} on any failure.
    """
    prompt = _CLASSIFICATION_PROMPT.format(message=message)

    for attempt in range(2):
        try:
            raw = client.chat(prompt, history=[])
            cleaned = _strip_fences(raw)
            result = json.loads(cleaned)

            intent = result.get("intent", "unknown")
            if intent not in _VALID_INTENTS:
                logger.warning("Unrecognised intent '%s', defaulting to 'chat'", intent)
                intent = "chat"

            params = result.get("params", {})
            if not isinstance(params, dict):
                params = {}

            logger.debug("Intent classified: %s params=%s", intent, params)
            return {"intent": intent, "params": params}

        except json.JSONDecodeError as exc:
            logger.warning("Intent JSON parse failure: %s", exc)
            break  # Retrying won't fix a parse error.
        except Exception as exc:
            if attempt == 0 and _is_transient(exc):
                logger.warning("Transient error during intent classification, retrying: %s", exc)
                continue
            logger.warning("Intent classification error: %s", exc)
            break

    return {"intent": "chat", "params": {}}
