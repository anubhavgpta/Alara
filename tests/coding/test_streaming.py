"""Unit tests for stream_to_repl — backend and Gemini are mocked."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alara.coding.models import CodingResult, CodingTask
from alara.coding.streaming import stream_to_repl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(tmp_path: Path) -> CodingTask:
    return CodingTask(
        intent="code_edit",
        description="Fix the null dereference",
        workdir=tmp_path,
        read_only=False,
    )


def _make_backend_mock(
    chunks: list[str],
    result: CodingResult,
) -> AsyncMock:
    """Return an AsyncMock backend whose run() emits *chunks* then returns *result*."""

    async def _run(task: CodingTask, on_chunk) -> CodingResult:
        for chunk in chunks:
            on_chunk(chunk)
        return result

    mock_backend = AsyncMock()
    mock_backend.run.side_effect = _run
    return mock_backend


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_to_repl_calls_backend_run(tmp_path: Path, mock_gemini: MagicMock) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(success=True, summary="")
    backend = _make_backend_mock(chunks=[], result=result)

    with patch("alara.coding.streaming.rich_print"):
        await stream_to_repl(backend, task, mock_gemini)

    backend.run.assert_called_once()
    _, call_kwargs = backend.run.call_args.args, backend.run.call_args.kwargs
    # First positional arg is the task
    assert backend.run.call_args.args[0] is task


@pytest.mark.asyncio
async def test_stream_to_repl_sets_summary_from_gemini(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(success=True, summary="")
    backend = _make_backend_mock(chunks=["output line"], result=result)
    mock_gemini.chat.return_value = "Two files edited; tests still pass."

    with patch("alara.coding.streaming.rich_print"):
        returned = await stream_to_repl(backend, task, mock_gemini)

    assert returned.summary == "Two files edited; tests still pass."


@pytest.mark.asyncio
async def test_stream_to_repl_passes_accumulated_output_to_gemini(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    chunks = ["Patching auth.py", "Writing test_auth.py", "Exit 0"]
    result = CodingResult(success=True, summary="")
    backend = _make_backend_mock(chunks=chunks, result=result)

    with patch("alara.coding.streaming.rich_print"):
        await stream_to_repl(backend, task, mock_gemini)

    # Gemini should be called once with a prompt containing the output lines
    mock_gemini.chat.assert_called_once()
    prompt_arg = mock_gemini.chat.call_args.args[0]
    for chunk in chunks:
        assert chunk in prompt_arg


@pytest.mark.asyncio
async def test_stream_to_repl_falls_back_on_gemini_error(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(success=True, summary="")
    backend = _make_backend_mock(chunks=["line"], result=result)
    mock_gemini.chat.side_effect = Exception("Gemini unavailable")

    with patch("alara.coding.streaming.rich_print"):
        returned = await stream_to_repl(backend, task, mock_gemini)

    # Must not raise; fallback summary must be non-empty
    assert returned.summary != ""


@pytest.mark.asyncio
async def test_stream_to_repl_fallback_summary_indicates_failure_on_error_result(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(
        success=False, summary="", error="aider crashed"
    )
    backend = _make_backend_mock(chunks=[], result=result)
    mock_gemini.chat.side_effect = Exception("unavailable")

    with patch("alara.coding.streaming.rich_print"):
        returned = await stream_to_repl(backend, task, mock_gemini)

    assert "aider crashed" in returned.summary or "failed" in returned.summary.lower()


@pytest.mark.asyncio
async def test_stream_to_repl_renders_diff_when_present(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    diff_text = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-bug\n+fix\n"
    result = CodingResult(success=True, summary="", diff=diff_text)
    backend = _make_backend_mock(chunks=[], result=result)

    with patch("alara.coding.streaming.rich_print"):
        with patch("alara.coding.streaming.Syntax") as mock_syntax:
            await stream_to_repl(backend, task, mock_gemini)

    # Syntax should be instantiated with the diff string and "diff" lexer
    mock_syntax.assert_called_once()
    call_args = mock_syntax.call_args
    assert call_args.args[0] == diff_text
    assert call_args.args[1] == "diff"


@pytest.mark.asyncio
async def test_stream_to_repl_does_not_render_syntax_when_no_diff(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(success=True, summary="", diff=None)
    backend = _make_backend_mock(chunks=[], result=result)

    with patch("alara.coding.streaming.rich_print"):
        with patch("alara.coding.streaming.Syntax") as mock_syntax:
            await stream_to_repl(backend, task, mock_gemini)

    mock_syntax.assert_not_called()


@pytest.mark.asyncio
async def test_stream_to_repl_returns_coding_result(
    tmp_path: Path, mock_gemini: MagicMock
) -> None:
    task = _make_task(tmp_path)
    result = CodingResult(success=True, summary="")
    backend = _make_backend_mock(chunks=[], result=result)

    with patch("alara.coding.streaming.rich_print"):
        returned = await stream_to_repl(backend, task, mock_gemini)

    assert isinstance(returned, CodingResult)
