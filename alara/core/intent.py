"""Intent classification for user messages."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from alara.core.gemini import GeminiClient

if TYPE_CHECKING:
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset(
    {
        # L0 intents
        "research",
        "file_read",
        "file_write",
        "file_list",
        "write_draft",
        "write_edit",
        # L1 external / Composio intents
        "comms_list",
        "comms_read",
        "comms_send",
        "comms_search",
        "calendar_list",
        "calendar_create",
        "task_list",
        "task_create",
        # L2 coding intents
        "code_edit",
        "code_create",
        "code_shell",
        "code_git",
        "code_review",
        # Background task intents
        "research_submit",
        "research_status",
        "research_fetch",
        "research_cancel",
        # L5 memory intents
        "memory_list",
        "memory_forget",
        "memory_clear",
        # L6 multi-agent orchestration intents
        "plan_create",
        "plan_status",
        # L7 dynamic MCP
        "generic_mcp",
        # L8 watcher intents
        "watch_add",
        "watch_list",
        "watch_remove",
        "watch_pause",
        "digest",
        # Fallback
        "chat",
        "unknown",
    }
)

_CLASSIFICATION_PROMPT = """\
You are an intent classifier for a personal desktop AI assistant called Alara.

Classify the following user message into exactly one of these intents:

Core intents:
- research       : user wants information, an explanation, or a knowledge-based answer
- file_read      : user wants to read or view the contents of a file
- file_write     : user wants to create, write, or save a file
- file_list      : user wants to list files or directories
- write_draft    : user wants a new piece of writing generated (email, essay, code, etc.)
- write_edit     : user wants to edit or improve existing text

External service intents (handled via Composio):
- comms_list     : user wants to list messages, emails, or notifications from any service
- comms_read     : user wants to read a specific message, email, or notification
- comms_send     : user wants to send a message or email via any service
- comms_search   : user wants to search messages or emails
- calendar_list  : user wants to list calendar events or see their schedule
- calendar_create: user wants to create or schedule a calendar event
- task_list      : user wants to list tasks, issues, or to-dos
- task_create    : user wants to create a new task, issue, or to-do item

Coding intents (handled via aider or OpenHands):
- code_edit      : user wants to edit, fix, refactor, modify, or update existing code
- code_create    : user wants to create, write, generate, or scaffold new code or files
- code_shell     : user wants to run, execute, install, or test via shell commands
- code_git       : user wants to commit, diff, status, push, log, or perform git operations
- code_review    : user wants to explain, review, summarise, or understand code (read-only)

Background task intents:
- research_submit: user wants to run research in the background, e.g. "research X in the background", "look into Y async", "background research on Z"
- research_status: user wants to check background task status, e.g. "what's the status of my tasks", "task status", "show my background tasks"
- research_fetch : user wants to retrieve a completed task result, e.g. "get results for task 3", "show me task 2", "fetch task result 5"
- research_cancel: user wants to cancel a background task, e.g. "cancel task 4", "stop task 2"

Memory intents:
- memory_list  : user wants to see all stored memories, e.g. "show my memories", "list memories", "what do you remember"
- memory_forget: user wants to delete a specific memory by ID, e.g. "forget memory 3", "delete memory 5"
- memory_clear : user wants to wipe all memories, e.g. "clear all memories", "forget everything", "reset memory"

Multi-agent orchestration intents:
- plan_create  : user wants to plan and execute a multi-step goal, e.g. "plan a goal", "orchestrate", "run a multi-step plan", "create a plan for", "plan out"
- plan_status  : user wants to see the current plan status, e.g. "plan status", "what is the plan status", "show plan progress"

Watcher intents:
- watch_add    : user wants to set up a recurring monitor or reminder, e.g. "watch for X", "remind me daily about Y", "every morning summarise Z", "monitor X"
- watch_list   : user wants to see their active watchers, e.g. "show my watchers", "list watchers", "what am I watching"
- watch_remove : user wants to delete a watcher, e.g. "remove watcher 3", "delete watcher 2"
- watch_pause  : user wants to pause a watcher, e.g. "pause watcher 2", "stop watcher 1 temporarily"
- digest       : user wants unsurfaced watcher results, e.g. "show digest", "what did I miss", "show me watcher results"

Fallback:
- chat           : general conversation, greetings, questions about Alara, small talk
- unknown        : cannot be classified into any of the above

Respond with ONLY a JSON object in this exact format (no markdown fences, no extra text):
{{"intent": "<intent>", "params": {{}}}}

Optionally populate "params" with extracted values:
- "path" and "content" for file_write (content = the exact text to write into the file)
- "path" for file_read and file_list
- "query" for research, comms_search
- "prompt" for write_draft
- "original" and "instructions" for write_edit
- "to", "subject", "body" for comms_send
- "message_id" or "subject" for comms_read
- "title", "date", "time", "attendees" for calendar_create
- "title", "description", "project" for task_create

User message: {message}
"""

class IntentParser:
    """Rule-based intent classifier — no network dependency.

    Uses ordered substring rules to map a user message to an intent string.
    Deterministic and suitable for unit tests.  For production classification
    use ``parse_intent()`` which delegates to Gemini.

    Rules are checked in declaration order; the first match wins.  All pattern
    comparisons are case-insensitive substring searches.
    """

    _RULES: list[tuple[str, list[str]]] = [
        # Most specific patterns first — first match wins.
        ("comms_search",    ["search email", "search message", "find email"]),
        ("comms_send",      ["send an email", "send email", "email to ", "send message"]),
        ("comms_read",      ["read the email", "read email", "open email", "read message"]),
        ("comms_list",      ["inbox", "my email", "my message", "check email", "list email", "show email"]),
        ("calendar_create", ["schedule a ", "create event", "add event", "book a meeting"]),
        ("calendar_list",   ["meetings", "my calendar", "my schedule", "upcoming event"]),
        ("task_create",     ["linear ticket", "create ticket", "create issue", "new ticket",
                             "new issue", "add a task", "create a task"]),
        ("task_list",       ["github issue", "open issue", "my tasks", "show issue",
                             "list task", "my issue"]),
        ("memory_clear",     ["clear all memories", "forget everything", "reset memory", "wipe memory"]),
        ("memory_forget",    ["forget memory", "delete memory", "remove memory"]),
        ("memory_list",      ["show my memories", "list memories", "what do you remember", "my memories"]),
        ("plan_status",      ["plan status", "what is the plan status", "show plan progress"]),
        ("plan_create",      ["plan a goal", "orchestrate", "run a multi-step plan", "create a plan",
                              "plan out", "multi-step"]),
        ("digest",           ["show digest", "what did i miss", "watcher results", "show me watcher"]),
        ("watch_remove",     ["remove watcher", "delete watcher", "stop watcher"]),
        ("watch_pause",      ["pause watcher"]),
        ("watch_list",       ["show my watchers", "list watchers", "what am i watching", "my watchers"]),
        ("watch_add",        ["watch for", "remind me daily", "every morning", "monitor ", "watch every"]),
        ("research_cancel",  ["cancel task", "stop task"]),
        ("research_fetch",   ["get results for task", "show me task", "fetch task result",
                              "results for task"]),
        ("research_status",  ["status of my tasks", "task status", "show my background tasks",
                              "background tasks", "my tasks status"]),
        ("research_submit",  ["research in the background", "background research",
                              "look into", "async research", "research async"]),
        ("code_git",        ["git commit", "git diff", "git status", "git push", "git pull",
                             "git log", "git show", "git blame", "git merge", "git rebase",
                             "git stash", "git branch", "git checkout", "git add"]),
        ("code_shell",      ["run the tests", "run tests", "npm install", "pip install",
                             "execute ", "run the script", "run script", "install dependencies",
                             "make build", "cargo build", "go build"]),
        ("code_review",     ["review this code", "explain this code", "explain the code",
                             "summarise the code", "summarize the code", "understand this code",
                             "what does this code", "walk me through"]),
        ("code_edit",       ["fix the bug", "fix bug", "refactor ", "edit the code",
                             "update the function", "modify ", "fix the error"]),
        ("code_create",     ["create a new file", "write a new", "scaffold ", "generate a",
                             "create a class", "write a function", "generate code"]),
        ("file_write",      ["write file", "create file", "save file"]),
        ("file_read",       ["read file", "show file", "open file", "view file"]),
        ("file_list",       ["list files", "list file", "show files", "files in "]),
        ("write_draft",     ["draft a", "draft an", "write an essay", "compose a"]),
        ("write_edit",      ["edit this", "rewrite this", "improve this"]),
        ("research",        ["research ", "explain ", "what is ", "tell me about ", "how does"]),
        ("chat",            ["hello", "hi there", "how are you", "hey alara"]),
    ]

    def classify(self, message: str) -> str:
        """Return the intent string that best matches *message*.

        Falls back to ``"chat"`` when no rule fires.
        """
        lower = message.lower()
        for intent, patterns in self._RULES:
            if any(p in lower for p in patterns):
                return intent
        return "chat"


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    return text.strip()


def _is_transient(exc: Exception) -> bool:
    """Return True for errors worth retrying (rate limit, service unavailable)."""
    msg = str(exc).upper()
    return any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))


_TOOL_MATCH_PROMPT = """\
Given these available tools:
{tool_list}
Which single tool best matches this request? Reply with ONLY the tool name, nothing else. \
If no tool matches, reply 'none'.

Request: {message}"""


def parse_intent(
    message: str,
    client: GeminiClient,
    session: "SessionContext | None" = None,
) -> dict:
    """Classify *message* into a structured intent dict.

    Retries once on transient API errors before falling back to "chat".
    When the intent is "unknown" and a service_registry is available on
    *session*, attempts to match the message to a discovered MCP tool.

    Returns:
        {"intent": str, "params": dict}
    """
    classification_prompt = _CLASSIFICATION_PROMPT.format(message=message)

    intent = "unknown"
    params: dict = {}

    for attempt in range(2):
        try:
            raw = client.chat(classification_prompt, history=[])
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
            break

        except json.JSONDecodeError as exc:
            logger.warning("Intent JSON parse failure: %s", exc)
            intent = "chat"
            break
        except Exception as exc:
            if attempt == 0 and _is_transient(exc):
                logger.warning(
                    "Transient error during intent classification, retrying: %s", exc
                )
                continue
            logger.warning("Intent classification error: %s", exc)
            intent = "chat"
            break

    if intent == "unknown" and session is not None and session.service_registry is not None:
        from alara.mcp.discovery import all_tools_flat

        flat = all_tools_flat(session.service_registry)
        if flat:
            tool_list = "\n".join(
                f"{m.name}: {m.description}" for m in flat
            )
            match_prompt = _TOOL_MATCH_PROMPT.format(
                tool_list=tool_list, message=message
            )
            try:
                response = client.chat(match_prompt, history=[]).strip()
                if response.lower() != "none" and response:
                    intent = "generic_mcp"
                    session.pending_mcp_tool = response.strip()
                    logger.debug(
                        "generic_mcp fallback matched tool: %s", session.pending_mcp_tool
                    )
                else:
                    intent = "chat"
            except Exception as exc:
                logger.warning("generic_mcp tool match failed: %s", exc)
                intent = "chat"
        else:
            intent = "chat"
    elif intent == "unknown":
        intent = "chat"

    return {"intent": intent, "params": params}
