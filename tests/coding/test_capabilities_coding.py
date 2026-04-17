"""Unit tests for alara.capabilities.coding — handle(), _check_permission(), helpers."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alara.capabilities.coding import (
    READ_GIT_OPS,
    _check_permission,
    _extract_git_subcmd,
)
from alara.coding.models import CodingResult
from alara.core.session import SessionContext


# ---------------------------------------------------------------------------
# _extract_git_subcmd helper
# ---------------------------------------------------------------------------


def test_extract_git_subcmd_from_explicit_git_prefix() -> None:
    assert _extract_git_subcmd("git commit -m 'fix'") == "commit"


def test_extract_git_subcmd_status() -> None:
    assert _extract_git_subcmd("git status") == "status"


def test_extract_git_subcmd_log() -> None:
    assert _extract_git_subcmd("show me git log") == "log"


def test_extract_git_subcmd_returns_none_for_no_git() -> None:
    result = _extract_git_subcmd("fix the bug in main.py")
    assert result is None or result not in READ_GIT_OPS


def test_read_git_ops_frozenset_contents() -> None:
    assert READ_GIT_OPS == {"status", "diff", "log", "show", "blame"}


# ---------------------------------------------------------------------------
# _check_permission helper
# ---------------------------------------------------------------------------


def test_check_permission_code_review_needs_no_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action") as mock_gate:
        result = _check_permission("code_review", "explain main.py", tmp_path)
    mock_gate.assert_not_called()
    assert result is True


def test_check_permission_code_git_read_op_needs_no_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action") as mock_gate:
        result = _check_permission("code_git", "git status", tmp_path)
    mock_gate.assert_not_called()
    assert result is True


def test_check_permission_code_git_diff_needs_no_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action") as mock_gate:
        result = _check_permission("code_git", "git diff HEAD", tmp_path)
    mock_gate.assert_not_called()
    assert result is True


def test_check_permission_code_git_write_op_triggers_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=True) as mock_gate:
        result = _check_permission("code_git", "git commit -m 'wip'", tmp_path)
    mock_gate.assert_called_once()
    assert result is True


def test_check_permission_code_git_write_op_denied(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=False):
        result = _check_permission("code_git", "git push origin main", tmp_path)
    assert result is False


def test_check_permission_code_edit_triggers_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=True) as mock_gate:
        _check_permission("code_edit", "fix the bug", tmp_path)
    mock_gate.assert_called_once()


def test_check_permission_code_edit_denied(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=False):
        result = _check_permission("code_edit", "fix the bug", tmp_path)
    assert result is False


def test_check_permission_code_create_triggers_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=True) as mock_gate:
        _check_permission("code_create", "scaffold a new module", tmp_path)
    mock_gate.assert_called_once()


def test_check_permission_code_shell_triggers_gate(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action", return_value=True) as mock_gate:
        _check_permission("code_shell", "run pytest", tmp_path)
    mock_gate.assert_called_once()


def test_check_permission_unknown_intent_denies(tmp_path: Path) -> None:
    with patch("alara.capabilities.coding.confirm_action"):
        result = _check_permission("mystery_intent", "do something", tmp_path)
    assert result is False


# ---------------------------------------------------------------------------
# handle() — workdir management
# ---------------------------------------------------------------------------


def _make_config(backend: str = "aider") -> dict:
    return {
        "coding": {
            "backend": backend,
            "aider_model": "gemini/gemini-2.5-flash",
            "openhands_base_url": "http://localhost:3000",
            "openhands_timeout_seconds": 30,
        }
    }


def _patch_stack(confirm: bool = True, workdir_input: str = ""):
    """Return a dict of patches needed to exercise handle() without real I/O.

    The ``pt_prompt`` entry patches the entire PromptSession class so that
    neither its __init__ (which requires a real Win32 console) nor its
    prompt_async method touch the terminal.  When used as ``with patches["pt_prompt"]
    as mock_pt:``, ``mock_pt`` is the mock class; ``mock_pt.assert_called_once()``
    verifies PromptSession() was instantiated and ``mock_pt.assert_not_called()``
    verifies it was not.
    """
    _pt_instance = MagicMock()
    _pt_instance.prompt_async = AsyncMock(return_value=workdir_input)
    _pt_class = MagicMock(return_value=_pt_instance)

    return {
        "stream": patch(
            "alara.capabilities.coding.stream_to_repl",
            new_callable=AsyncMock,
            return_value=CodingResult(success=True, summary="done"),
        ),
        "extract": patch(
            "alara.capabilities.coding._extract_files",
            return_value=[],
        ),
        "gate": patch(
            "alara.capabilities.coding.confirm_action",
            return_value=confirm,
        ),
        "avail": patch(
            "alara.coding.aider_backend.AiderBackend.is_available",
            new_callable=AsyncMock,
            return_value=True,
        ),
        "pt_prompt": patch("prompt_toolkit.PromptSession", _pt_class),
    }


@pytest.mark.asyncio
async def test_handle_calls_stream_to_repl_for_code_edit(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=True)
    with patches["stream"] as mock_stream, patches["extract"], patches["gate"], patches["avail"]:
        from alara.capabilities.coding import handle
        await handle("code_edit", "fix the bug", empty_coding_session, mock_gemini, _make_config())
    mock_stream.assert_called_once()


@pytest.mark.asyncio
async def test_handle_does_not_call_backend_when_gate_denied(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=False)
    with patches["stream"] as mock_stream, patches["extract"], patches["gate"], patches["avail"]:
        from alara.capabilities.coding import handle
        await handle("code_edit", "fix the bug", empty_coding_session, mock_gemini, _make_config())
    mock_stream.assert_not_called()


@pytest.mark.asyncio
async def test_handle_code_review_skips_gate(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=False)  # gate says no, but review bypasses it
    with (
        patches["stream"] as mock_stream,
        patches["extract"],
        patches["gate"] as mock_gate,
        patches["avail"],
        patch("alara.capabilities.coding._run_code_review") as mock_review,
    ):
        from alara.capabilities.coding import handle
        await handle("code_review", "explain main.py", empty_coding_session, mock_gemini, _make_config())
    mock_gate.assert_not_called()
    mock_stream.assert_not_called()   # review bypasses aider entirely
    mock_review.assert_called_once()


@pytest.mark.asyncio
async def test_handle_resets_workdir_on_reset_dir_flag(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    # pre-set the workdir
    empty_coding_session.coding_workdir = Path("/old/dir")
    patches = _patch_stack(confirm=True, workdir_input=str(empty_coding_session.coding_workdir))
    with patches["stream"], patches["extract"], patches["gate"], patches["avail"], patches["pt_prompt"]:
        from alara.capabilities.coding import handle
        await handle(
            "code_edit",
            "/code --reset-dir fix the bug",
            empty_coding_session,
            mock_gemini,
            _make_config(),
        )
    # After reset, the prompt fired and workdir was re-set (or kept from prompt)
    # The key invariant: coding_workdir is not None after handle()
    assert empty_coding_session.coding_workdir is not None


@pytest.mark.asyncio
async def test_handle_prompts_for_workdir_when_none(
    session_no_workdir: SessionContext, mock_gemini: MagicMock, tmp_path: Path
) -> None:
    assert session_no_workdir.coding_workdir is None
    patches = _patch_stack(confirm=True, workdir_input=str(tmp_path))
    with (
        patches["stream"],
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patches["pt_prompt"] as mock_pt,
        patch("alara.capabilities.coding._run_code_review"),
    ):
        from alara.capabilities.coding import handle
        await handle("code_review", "explain main.py", session_no_workdir, mock_gemini, _make_config())
    mock_pt.assert_called_once()
    assert session_no_workdir.coding_workdir is not None


@pytest.mark.asyncio
async def test_handle_does_not_prompt_when_workdir_already_set(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    assert empty_coding_session.coding_workdir is not None
    patches = _patch_stack(confirm=True)
    with (
        patches["stream"],
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patches["pt_prompt"] as mock_pt,
        patch("alara.capabilities.coding._run_code_review"),
    ):
        from alara.capabilities.coding import handle
        await handle("code_review", "explain main.py", empty_coding_session, mock_gemini, _make_config())
    mock_pt.assert_not_called()


@pytest.mark.asyncio
async def test_handle_prints_error_when_backend_unavailable(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=True)
    printed: list[str] = []
    with (
        patches["stream"] as mock_stream,
        patches["extract"],
        patches["gate"],
        patch(
            "alara.coding.aider_backend.AiderBackend.is_available",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("alara.capabilities.coding.rich_print", side_effect=printed.append),
    ):
        from alara.capabilities.coding import handle
        await handle("code_edit", "fix bug", empty_coding_session, mock_gemini, _make_config())
    mock_stream.assert_not_called()
    assert any("not available" in str(m).lower() for m in printed)


@pytest.mark.asyncio
async def test_handle_constructs_task_with_correct_intent(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=True)
    with patches["stream"] as mock_stream, patches["extract"], patches["gate"], patches["avail"]:
        from alara.capabilities.coding import handle
        await handle("code_edit", "fix the type error", empty_coding_session, mock_gemini, _make_config())

    # stream_to_repl receives (backend, task, gemini_client)
    task_arg = mock_stream.call_args.args[1]
    assert task_arg.intent == "code_edit"


@pytest.mark.asyncio
async def test_handle_code_review_calls_run_code_review(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    """code_review must call _run_code_review with (user_input, files, workdir, gemini)."""
    patches = _patch_stack(confirm=True)
    with (
        patches["stream"] as mock_stream,
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_code_review") as mock_review,
    ):
        from alara.capabilities.coding import handle
        await handle("code_review", "explain main.py", empty_coding_session, mock_gemini, _make_config())

    mock_stream.assert_not_called()
    mock_review.assert_called_once()
    # Third positional arg is workdir
    assert mock_review.call_args.args[2] == empty_coding_session.coding_workdir


@pytest.mark.asyncio
async def test_handle_sets_read_only_false_for_non_review(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=True)
    with patches["stream"] as mock_stream, patches["extract"], patches["gate"], patches["avail"]:
        from alara.capabilities.coding import handle
        await handle("code_edit", "fix bug", empty_coding_session, mock_gemini, _make_config())

    task_arg = mock_stream.call_args.args[1]
    assert task_arg.read_only is False


# ---------------------------------------------------------------------------
# handle() — code_git routes directly, not through aider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_code_git_does_not_call_backend(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    """Git commands must bypass aider entirely and run git directly."""
    patches = _patch_stack(confirm=True)
    with (
        patches["stream"] as mock_stream,
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_git_direct", new_callable=AsyncMock) as mock_git,
    ):
        from alara.capabilities.coding import handle
        await handle("code_git", "git status", empty_coding_session, mock_gemini, _make_config())

    mock_stream.assert_not_called()
    mock_git.assert_called_once()


@pytest.mark.asyncio
async def test_handle_code_git_passes_workdir(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=True)
    with (
        patches["stream"],
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_git_direct", new_callable=AsyncMock) as mock_git,
    ):
        from alara.capabilities.coding import handle
        await handle("code_git", "git diff HEAD", empty_coding_session, mock_gemini, _make_config())

    _, kwargs = mock_git.call_args.args, mock_git.call_args.kwargs
    workdir_arg = mock_git.call_args.args[1]
    assert workdir_arg == empty_coding_session.coding_workdir


@pytest.mark.asyncio
async def test_handle_code_git_write_op_denied_skips_git(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    """If the user denies a write git op, _run_git_direct must not be called."""
    patches = _patch_stack(confirm=False)
    with (
        patches["stream"],
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_git_direct", new_callable=AsyncMock) as mock_git,
    ):
        from alara.capabilities.coding import handle
        await handle("code_git", "git commit -m 'wip'", empty_coding_session, mock_gemini, _make_config())

    mock_git.assert_not_called()


# ---------------------------------------------------------------------------
# handle() — code_shell routes directly, not through aider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_code_shell_does_not_call_backend(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    """Shell commands must bypass aider and run directly."""
    patches = _patch_stack(confirm=True)
    with (
        patches["stream"] as mock_stream,
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_shell_direct", new_callable=AsyncMock) as mock_shell,
    ):
        from alara.capabilities.coding import handle
        await handle("code_shell", "run python main.py", empty_coding_session, mock_gemini, _make_config())

    mock_stream.assert_not_called()
    mock_shell.assert_called_once()


@pytest.mark.asyncio
async def test_handle_code_shell_denied_skips_shell(
    empty_coding_session: SessionContext, mock_gemini: MagicMock
) -> None:
    patches = _patch_stack(confirm=False)
    with (
        patches["stream"],
        patches["extract"],
        patches["gate"],
        patches["avail"],
        patch("alara.capabilities.coding._run_shell_direct", new_callable=AsyncMock) as mock_shell,
    ):
        from alara.capabilities.coding import handle
        await handle("code_shell", "run pytest", empty_coding_session, mock_gemini, _make_config())

    mock_shell.assert_not_called()


# ---------------------------------------------------------------------------
# _parse_shell_cmd
# ---------------------------------------------------------------------------


def test_parse_shell_cmd_strips_run_prefix() -> None:
    from alara.capabilities.coding import _parse_shell_cmd
    assert _parse_shell_cmd("run python main.py") == ["python", "main.py"]


def test_parse_shell_cmd_strips_execute_prefix() -> None:
    from alara.capabilities.coding import _parse_shell_cmd
    assert _parse_shell_cmd("execute pytest -v") == ["pytest", "-v"]


def test_parse_shell_cmd_no_prefix_passthrough() -> None:
    from alara.capabilities.coding import _parse_shell_cmd
    assert _parse_shell_cmd("python main.py") == ["python", "main.py"]


def test_parse_shell_cmd_handles_flags() -> None:
    from alara.capabilities.coding import _parse_shell_cmd
    result = _parse_shell_cmd("run pytest -v tests/")
    assert result == ["pytest", "-v", "tests/"]


def test_parse_shell_cmd_empty_returns_none() -> None:
    from alara.capabilities.coding import _parse_shell_cmd
    assert _parse_shell_cmd("") is None


# ---------------------------------------------------------------------------
# _extract_git_cmd — Gemini translation + heuristic fallback
# ---------------------------------------------------------------------------


def test_extract_git_cmd_uses_gemini_response(mock_gemini: MagicMock) -> None:
    from alara.capabilities.coding import _extract_git_cmd
    mock_gemini.chat.return_value = 'git commit -m "add calculator"'
    result = _extract_git_cmd("git commit with message 'add calculator'", mock_gemini)
    assert result == ["git", "commit", "-m", "add calculator"]


def test_extract_git_cmd_falls_back_on_non_git_response(mock_gemini: MagicMock) -> None:
    from alara.capabilities.coding import _extract_git_cmd
    mock_gemini.chat.return_value = "Sure, here is the command: git status"
    result = _extract_git_cmd("git status", mock_gemini)
    # Fallback heuristic kicks in — still produces a valid git command
    assert result[0] == "git"


def test_extract_git_cmd_falls_back_on_gemini_error(mock_gemini: MagicMock) -> None:
    from alara.capabilities.coding import _extract_git_cmd
    mock_gemini.chat.side_effect = Exception("Gemini unavailable")
    result = _extract_git_cmd("git status", mock_gemini)
    assert result == ["git", "status"]


def test_extract_git_cmd_natural_language_diff(mock_gemini: MagicMock) -> None:
    from alara.capabilities.coding import _extract_git_cmd
    mock_gemini.chat.return_value = "git log --oneline -5"
    result = _extract_git_cmd("show me the last 5 commits", mock_gemini)
    assert result == ["git", "log", "--oneline", "-5"]


# ---------------------------------------------------------------------------
# _run_git_direct / _run_shell_direct — async check
# ---------------------------------------------------------------------------


def test_run_git_direct_is_async() -> None:
    import inspect
    from alara.capabilities.coding import _run_git_direct
    assert inspect.iscoroutinefunction(_run_git_direct)


def test_run_shell_direct_is_async() -> None:
    import inspect
    from alara.capabilities.coding import _run_shell_direct
    assert inspect.iscoroutinefunction(_run_shell_direct)
