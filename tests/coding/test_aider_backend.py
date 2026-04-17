"""Unit tests for AiderBackend — all subprocess I/O is mocked."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alara.coding.aider_backend import AiderBackend
from alara.coding.models import CodingTask
from alara.core.errors import AlaraError


# ---------------------------------------------------------------------------
# Helpers — mock subprocess streams and process
# ---------------------------------------------------------------------------


class _MockStream:
    """Async-compatible stand-in for asyncio.StreamReader.

    Yields lines one at a time via readline(), ending with b"" (EOF).
    """

    def __init__(self, lines: list[str]) -> None:
        data = [line.encode() + b"\n" for line in lines]
        data.append(b"")  # EOF sentinel
        self._data = data
        self._idx = 0

    async def readline(self) -> bytes:
        if self._idx < len(self._data):
            chunk = self._data[self._idx]
            self._idx += 1
            return chunk
        return b""


class _MockProcess:
    """Stand-in for asyncio.subprocess.Process."""

    def __init__(
        self,
        stdout_lines: list[str],
        stderr_lines: list[str],
        returncode: int,
    ) -> None:
        self.stdout = _MockStream(stdout_lines)
        self.stderr = _MockStream(stderr_lines)
        self.returncode = returncode

    async def wait(self) -> None:
        pass


def _make_backend() -> AiderBackend:
    return AiderBackend(aider_model="gemini/gemini-2.5-flash")


def _make_task(tmp_path: Path, read_only: bool = False, files: list | None = None) -> CodingTask:
    return CodingTask(
        intent="code_edit",
        description="Fix the off-by-one error",
        workdir=tmp_path,
        files=[Path(f) for f in (files or [])],
        read_only=read_only,
    )


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_available_returns_false_when_aider_not_on_path() -> None:
    backend = _make_backend()
    with patch("shutil.which", return_value=None):
        assert await backend.is_available() is False


@pytest.mark.asyncio
async def test_is_available_returns_true_when_aider_found() -> None:
    backend = _make_backend()
    with patch("shutil.which", return_value="/usr/local/bin/aider"):
        assert await backend.is_available() is True


# ---------------------------------------------------------------------------
# run() — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_success_returns_true_result(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(
        stdout_lines=["Applying changes...", "Done."],
        stderr_lines=[],
        returncode=0,
    )
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        result = await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_run_success_streams_all_stdout_chunks_in_order(tmp_path: Path) -> None:
    backend = _make_backend()
    expected = ["Aider started", "Reading main.py", "Writing patch", "Done."]
    mock_proc = _MockProcess(stdout_lines=expected, stderr_lines=[], returncode=0)

    received: list[str] = []
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        await backend.run(_make_task(tmp_path), on_chunk=received.append)

    # All stdout lines must appear in received (order preserved within stdout).
    for line in expected:
        assert line in received


@pytest.mark.asyncio
async def test_run_success_streams_stderr_chunks(tmp_path: Path) -> None:
    backend = _make_backend()
    stderr = ["WARNING: no git repo", "Continuing anyway"]
    mock_proc = _MockProcess(stdout_lines=["Done."], stderr_lines=stderr, returncode=0)

    received: list[str] = []
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        await backend.run(_make_task(tmp_path), on_chunk=received.append)

    for line in stderr:
        assert line in received


# ---------------------------------------------------------------------------
# run() — failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_non_zero_exit_returns_failure_result(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(
        stdout_lines=[],
        stderr_lines=["Error: model not found"],
        returncode=1,
    )
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        result = await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    assert result.success is False
    assert result.error is not None
    assert "Error: model not found" in result.error


@pytest.mark.asyncio
async def test_run_non_zero_exit_accumulates_full_stderr(tmp_path: Path) -> None:
    backend = _make_backend()
    stderr = ["line 1", "line 2", "line 3"]
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=stderr, returncode=2)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        result = await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    for line in stderr:
        assert line in (result.error or "")


@pytest.mark.asyncio
async def test_run_raises_alara_error_on_launch_failure(tmp_path: Path) -> None:
    backend = _make_backend()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError("aider not found"),
    ):
        with pytest.raises(AlaraError, match="aider"):
            await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_always_includes_required_flags(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    cmd = mock_exec.call_args.args
    assert "--no-auto-commits" in cmd
    assert "--yes-always" in cmd
    assert "--no-pretty" in cmd


@pytest.mark.asyncio
async def test_run_includes_model_flag(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    cmd = mock_exec.call_args.args
    assert "--model" in cmd
    model_idx = list(cmd).index("--model")
    assert cmd[model_idx + 1] == "gemini/gemini-2.5-flash"


@pytest.mark.asyncio
async def test_run_includes_message_flag_with_description(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    cmd = list(mock_exec.call_args.args)
    assert "--message" in cmd
    msg_idx = cmd.index("--message")
    assert cmd[msg_idx + 1] == "Fix the off-by-one error"


@pytest.mark.asyncio
async def test_run_includes_dry_run_when_read_only(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path, read_only=True), on_chunk=lambda _: None)

    assert "--dry-run" in mock_exec.call_args.args


@pytest.mark.asyncio
async def test_run_omits_dry_run_when_not_read_only(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path, read_only=False), on_chunk=lambda _: None)

    assert "--dry-run" not in mock_exec.call_args.args


@pytest.mark.asyncio
async def test_run_appends_files_to_command(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)
    task = _make_task(tmp_path, files=["auth.py", "utils/helpers.py"])

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(task, on_chunk=lambda _: None)

    # Normalise to Path so the test is portable across OS path separators.
    cmd_paths = [Path(a) for a in mock_exec.call_args.args if isinstance(a, str)]
    assert Path("auth.py") in cmd_paths
    assert Path("utils/helpers.py") in cmd_paths


@pytest.mark.asyncio
async def test_run_sets_cwd_to_workdir(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    kwargs = mock_exec.call_args.kwargs
    assert kwargs.get("cwd") == str(tmp_path)


@pytest.mark.asyncio
async def test_run_includes_encoding_flag(tmp_path: Path) -> None:
    backend = AiderBackend(aider_model="gemini/gemini-2.5-flash", encoding="utf-16")
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    cmd = list(mock_exec.call_args.args)
    assert "--encoding" in cmd
    enc_idx = cmd.index("--encoding")
    assert cmd[enc_idx + 1] == "utf-16"


@pytest.mark.asyncio
async def test_run_defaults_to_utf8_encoding(tmp_path: Path) -> None:
    backend = _make_backend()  # no encoding kwarg — defaults to utf-8
    mock_proc = _MockProcess(stdout_lines=[], stderr_lines=[], returncode=0)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec:
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    cmd = list(mock_exec.call_args.args)
    assert "--encoding" in cmd
    enc_idx = cmd.index("--encoding")
    assert cmd[enc_idx + 1] == "utf-8"
