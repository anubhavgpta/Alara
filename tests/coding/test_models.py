"""Unit tests for alara.coding.models — CodingTask and CodingResult."""

from pathlib import Path

import pytest

from alara.coding.models import CodingResult, CodingTask


# ---------------------------------------------------------------------------
# CodingTask
# ---------------------------------------------------------------------------


def test_coding_task_stores_all_fields(tmp_path: Path) -> None:
    task = CodingTask(
        intent="code_edit",
        description="Refactor the login function",
        workdir=tmp_path,
        files=[Path("auth.py"), Path("utils.py")],
        read_only=False,
    )
    assert task.intent == "code_edit"
    assert task.description == "Refactor the login function"
    assert task.workdir == tmp_path
    assert task.files == [Path("auth.py"), Path("utils.py")]
    assert task.read_only is False


def test_coding_task_default_files_is_empty_list(tmp_path: Path) -> None:
    task = CodingTask(
        intent="code_create",
        description="Scaffold a new module",
        workdir=tmp_path,
    )
    assert task.files == []


def test_coding_task_default_read_only_is_false(tmp_path: Path) -> None:
    task = CodingTask(
        intent="code_shell",
        description="Run pytest",
        workdir=tmp_path,
    )
    assert task.read_only is False


def test_coding_task_read_only_true_propagates(tmp_path: Path) -> None:
    task = CodingTask(
        intent="code_review",
        description="Explain main.py",
        workdir=tmp_path,
        read_only=True,
    )
    assert task.read_only is True


def test_coding_task_accepts_pathlib_path_for_workdir(tmp_path: Path) -> None:
    task = CodingTask(intent="code_git", description="git status", workdir=tmp_path)
    assert isinstance(task.workdir, Path)


def test_coding_task_files_list_is_not_shared_across_instances(tmp_path: Path) -> None:
    """Mutable default: each instance must own its own list."""
    task_a = CodingTask(intent="code_edit", description="a", workdir=tmp_path)
    task_b = CodingTask(intent="code_edit", description="b", workdir=tmp_path)
    task_a.files.append(Path("foo.py"))
    assert task_b.files == []


# ---------------------------------------------------------------------------
# CodingResult
# ---------------------------------------------------------------------------


def test_coding_result_success_fields() -> None:
    result = CodingResult(
        success=True,
        summary="Three files modified.",
        diff="--- a/main.py\n+++ b/main.py\n",
        shell_output=None,
        error=None,
    )
    assert result.success is True
    assert result.summary == "Three files modified."
    assert result.diff is not None
    assert result.error is None


def test_coding_result_failure_fields() -> None:
    result = CodingResult(
        success=False,
        summary="",
        diff=None,
        shell_output=None,
        error="aider: command not found",
    )
    assert result.success is False
    assert result.error == "aider: command not found"
    assert result.diff is None


def test_coding_result_defaults_are_none() -> None:
    result = CodingResult(success=True, summary="ok")
    assert result.diff is None
    assert result.shell_output is None
    assert result.error is None


def test_coding_result_with_shell_output() -> None:
    result = CodingResult(
        success=True,
        summary="Tests passed.",
        shell_output="....\n4 passed in 0.12s",
    )
    assert result.shell_output is not None
    assert "passed" in result.shell_output


def test_coding_result_summary_can_be_empty_string() -> None:
    result = CodingResult(success=True, summary="")
    assert result.summary == ""
