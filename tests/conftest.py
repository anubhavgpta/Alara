"""Shared pytest fixtures for the Alara test suite."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alara.coding.models import CodingResult, CodingTask
from alara.core.session import SessionContext


# ---------------------------------------------------------------------------
# SessionContext fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_coding_session(tmp_path: Path) -> SessionContext:
    """SessionContext with coding_workdir pre-set to a real tmp directory."""
    return SessionContext(
        composio_mcp_url="",
        active_toolkits=[],
        available_tools=[],
        active_tools=[],
        started_at=datetime.utcnow(),
        coding_workdir=tmp_path,
        coding_backend="aider",
    )


@pytest.fixture
def session_no_workdir() -> SessionContext:
    """SessionContext with coding_workdir=None (triggers prompt in handle())."""
    return SessionContext(
        composio_mcp_url="",
        active_toolkits=[],
        available_tools=[],
        active_tools=[],
        started_at=datetime.utcnow(),
        coding_workdir=None,
        coding_backend=None,
    )


# ---------------------------------------------------------------------------
# GeminiClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gemini() -> MagicMock:
    """A MagicMock standing in for GeminiClient.

    chat() returns a generic summary string by default.
    Tests that need specific Gemini responses can override .return_value.
    """
    client = MagicMock()
    client.chat.return_value = "Mocked Gemini summary."
    return client


# ---------------------------------------------------------------------------
# CodingTask fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def edit_task(tmp_path: Path) -> CodingTask:
    """A standard code_edit CodingTask for reuse across tests."""
    return CodingTask(
        intent="code_edit",
        description="Fix the off-by-one error in main.py",
        workdir=tmp_path,
        files=[Path("main.py")],
        read_only=False,
    )


@pytest.fixture
def review_task(tmp_path: Path) -> CodingTask:
    """A read-only code_review CodingTask."""
    return CodingTask(
        intent="code_review",
        description="Explain what main.py does",
        workdir=tmp_path,
        files=[],
        read_only=True,
    )


# ---------------------------------------------------------------------------
# CodingResult helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def success_result() -> CodingResult:
    return CodingResult(
        success=True,
        summary="Task completed without errors.",
        diff=None,
        shell_output=None,
        error=None,
    )


@pytest.fixture
def failure_result() -> CodingResult:
    return CodingResult(
        success=False,
        summary="",
        diff=None,
        shell_output=None,
        error="stderr: command not found",
    )
