"""Route intents to the appropriate capability handler."""

import logging

from alara.capabilities import files, research, writing
from alara.core.gemini import GeminiClient

logger = logging.getLogger(__name__)


def dispatch(intent: dict, message: str, client: GeminiClient, config: dict) -> str:
    """Dispatch an intent to the matching capability and return a response string.

    Never raises to the caller — all exceptions are caught and returned as
    user-friendly error strings.

    Args:
        intent: Dict with keys "intent" (str) and "params" (dict).
        message: The original user message (used for chat/unknown fallback).
        client: Initialised GeminiClient instance.
        config: Loaded alara.toml config dict.

    Returns:
        A response string suitable for display in the REPL.
    """
    intent_name = intent.get("intent", "chat")
    params = intent.get("params", {})

    try:
        if intent_name == "research":
            query = params.get("query", message)
            return research.research(query, client)

        if intent_name == "file_read":
            path = params.get("path", message)
            return files.read_file(path)

        if intent_name == "file_write":
            path = params.get("path", "")
            content = params.get("content", message)
            if not path:
                return "File write requested but no path was identified. Please specify a file path."
            return files.write_file(path, content)

        if intent_name == "file_list":
            directory = params.get("path", params.get("directory", ""))
            # If Gemini returned a vague word ("workspace", "my workspace",
            # "home", etc.) rather than an actual path, treat it as the
            # workspace root.  A real path will contain a separator or start
            # with a drive letter / ~ / dot.
            if directory and not any(
                c in directory for c in (r"/", "\\", "~", ".")
            ) and ":" not in directory:
                logger.debug(
                    "file_list path %r looks like natural language, defaulting to workspace root",
                    directory,
                )
                directory = ""
            return files.list_files(directory)

        if intent_name == "write_draft":
            prompt = params.get("prompt", message)
            return writing.draft(prompt, client)

        if intent_name == "write_edit":
            original = params.get("original", message)
            instructions = params.get("instructions", "")
            if not instructions:
                return "Edit requested but no instructions were identified. Please describe the changes you want."
            return writing.edit(original, instructions, client)

        # "chat" and "unknown" both fall through to direct Gemini chat
        logger.debug("Dispatching to chat fallback for intent: %s", intent_name)
        return client.chat(message, history=[])

    except PermissionError as exc:
        logger.warning("Permission error during dispatch: %s", exc)
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.exception("Unhandled error during dispatch for intent '%s'", intent_name)
        return f"An error occurred while processing your request: {exc}"
