"""Intent classification for user messages."""

import json
import logging
import re

from alara.core.gemini import GeminiClient

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


def parse_intent(message: str, client: GeminiClient) -> dict:
    """Classify *message* into a structured intent dict.

    Retries once on transient API errors before falling back to "chat".

    Returns:
        {"intent": str, "params": dict}
    """
    classification_prompt = _CLASSIFICATION_PROMPT.format(message=message)

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
            return {"intent": intent, "params": params}

        except json.JSONDecodeError as exc:
            logger.warning("Intent JSON parse failure: %s", exc)
            break
        except Exception as exc:
            if attempt == 0 and _is_transient(exc):
                logger.warning(
                    "Transient error during intent classification, retrying: %s", exc
                )
                continue
            logger.warning("Intent classification error: %s", exc)
            break

    return {"intent": "chat", "params": {}}
