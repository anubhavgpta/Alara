"""Extract memories and summaries from session transcripts via Gemini."""

import json
import logging

from alara.core.gemini import GeminiClient
from alara.memory.store import save_memory, save_session_summary

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = (
    "You are a memory extraction assistant. Given a conversation transcript, "
    "extract discrete facts worth remembering as key-value pairs. Focus on: "
    "user name/location/role, project names and descriptions, technology "
    "preferences, file paths, recurring patterns. Return ONLY a JSON array of "
    '{\"key\": str, \"value\": str} objects. No markdown fences, no explanation, '
    "no preamble."
)

_SUMMARISE_PROMPT = (
    "Summarise this conversation in 3-5 bullet points describing what was "
    "accomplished. Be concise and factual. No preamble."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop opening fence line
        lines = lines[1:]
        # drop closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _format_transcript(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


async def extract_memories(
    session_id: int,
    messages: list[dict],
    gemini_client: GeminiClient,
) -> list[dict]:
    if not messages:
        return []

    transcript = _format_transcript(messages)
    prompt = f"{_EXTRACT_PROMPT}\n\nTranscript:\n{transcript}"

    try:
        response = gemini_client.chat(prompt, history=[])
        cleaned = _strip_fences(response)
        facts: list[dict] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Memory extraction parse failure: %s", exc)
        return []
    except Exception as exc:
        logger.warning("Memory extraction failed: %s", exc)
        return []

    saved: list[dict] = []
    for fact in facts:
        if isinstance(fact, dict) and "key" in fact and "value" in fact:
            save_memory(session_id, str(fact["key"]), str(fact["value"]), source="auto")
            saved.append(fact)

    logger.debug("Extracted %d memories for session %d", len(saved), session_id)
    return saved


async def summarise_session(
    session_id: int,
    messages: list[dict],
    gemini_client: GeminiClient,
) -> str:
    if not messages:
        return ""

    try:
        transcript = _format_transcript(messages)
        prompt = f"{_SUMMARISE_PROMPT}\n\nTranscript:\n{transcript}"
        summary = gemini_client.chat(prompt, history=[])
        save_session_summary(session_id, summary)
        logger.debug("Saved session summary for session %d", session_id)
        return summary
    except Exception as exc:
        logger.warning("Session summarisation failed: %s", exc)
        return ""
