import json
from unittest.mock import MagicMock

from alara.core.intent import IntentParser, _VALID_INTENTS, parse_intent

parser = IntentParser()

def test_comms_intents():
    assert parser.classify("show me my inbox") == "comms_list"
    assert parser.classify("read the email from Sarah") == "comms_read"
    assert parser.classify("send an email to dan@example.com") == "comms_send"
    assert parser.classify("search emails about invoice") == "comms_search"

def test_calendar_intents():
    assert parser.classify("what meetings do I have tomorrow") == "calendar_list"
    assert parser.classify("schedule a call with Priya on Friday") == "calendar_create"

def test_task_intents():
    assert parser.classify("show my open GitHub issues") == "task_list"
    assert parser.classify("create a Linear ticket for the login bug") == "task_create"

def test_l0_intents_unchanged():
    assert parser.classify("research quantum computing") == "research"
    assert parser.classify("list files in my workspace") == "file_list"
    assert parser.classify("hello how are you") == "chat"


# ---------------------------------------------------------------------------
# L2 coding intents — rule-based classifier (IntentParser)
# ---------------------------------------------------------------------------


def test_code_edit_rule_matches_fix_bug():
    assert parser.classify("fix the bug in utils.py") == "code_edit"

def test_code_edit_rule_matches_refactor():
    assert parser.classify("refactor the auth module") == "code_edit"

def test_code_create_rule_matches_generate():
    assert parser.classify("generate a FastAPI health endpoint") == "code_create"

def test_code_create_rule_matches_scaffold():
    assert parser.classify("scaffold a new Django app") == "code_create"

def test_code_create_rule_matches_write_function():
    assert parser.classify("write a function to parse JSON") == "code_create"

def test_code_shell_rule_matches_run_tests():
    assert parser.classify("run tests for the project") == "code_shell"

def test_code_shell_rule_matches_pip_install():
    assert parser.classify("pip install the new dependency") == "code_shell"

def test_code_git_rule_matches_git_commit():
    assert parser.classify("git commit my changes") == "code_git"

def test_code_git_rule_matches_git_status():
    assert parser.classify("git status") == "code_git"

def test_code_git_rule_matches_git_diff():
    assert parser.classify("git diff HEAD") == "code_git"

def test_code_review_rule_matches_explain_code():
    assert parser.classify("explain this code") == "code_review"

def test_code_review_rule_matches_review():
    assert parser.classify("review this code before I merge") == "code_review"

def test_code_review_rule_matches_summarise():
    assert parser.classify("summarize the code in main.py") == "code_review"


# ---------------------------------------------------------------------------
# L2 coding intents — Gemini-based classifier (parse_intent, mocked)
# The spec table: mock GeminiClient.chat() to return the expected intent JSON
# so the tests remain fast and deterministic.
# ---------------------------------------------------------------------------


def _mock_client(intent: str) -> MagicMock:
    """Return a GeminiClient mock whose chat() yields a specific intent JSON."""
    client = MagicMock()
    client.chat.return_value = json.dumps({"intent": intent, "params": {}})
    return client


def test_parse_intent_code_edit_from_gemini():
    result = parse_intent("fix the bug in utils.py", _mock_client("code_edit"))
    assert result["intent"] == "code_edit"

def test_parse_intent_code_create_from_gemini():
    result = parse_intent("create a FastAPI health endpoint", _mock_client("code_create"))
    assert result["intent"] == "code_create"

def test_parse_intent_code_shell_from_gemini():
    result = parse_intent("run pytest", _mock_client("code_shell"))
    assert result["intent"] == "code_shell"

def test_parse_intent_code_git_from_gemini():
    result = parse_intent("git commit my changes", _mock_client("code_git"))
    assert result["intent"] == "code_git"

def test_parse_intent_code_review_from_gemini():
    result = parse_intent("explain what main.py does", _mock_client("code_review"))
    assert result["intent"] == "code_review"

def test_all_coding_intents_in_valid_set():
    for intent in ("code_edit", "code_create", "code_shell", "code_git", "code_review"):
        assert intent in _VALID_INTENTS, f"{intent!r} missing from _VALID_INTENTS"

def test_parse_intent_falls_back_to_chat_on_unknown_coding_intent():
    """Gemini returning an unrecognised intent must degrade gracefully."""
    result = parse_intent("do something weird", _mock_client("code_telepathy"))
    assert result["intent"] == "chat"
