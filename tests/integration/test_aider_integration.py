"""Integration test for AiderBackend — requires `aider` installed on PATH.

Run with:
    pytest tests/integration/test_aider_integration.py -v

Skipped automatically when aider is not installed.
"""

import shutil
from pathlib import Path

import pytest

from alara.coding.aider_backend import AiderBackend
from alara.coding.models import CodingTask

pytestmark = pytest.mark.skipif(
    shutil.which("aider") is None,
    reason="aider not installed — pip install aider-chat to enable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_buggy_file(path: Path) -> Path:
    """Write a Python file with a deliberate off-by-one bug."""
    src = path / "buggy.py"
    src.write_text(
        "def sum_range(n: int) -> int:\n"
        "    # BUG: should be range(n+1) to include n\n"
        "    return sum(range(n))\n",
        encoding="utf-8",
    )
    return src


def _make_backend() -> AiderBackend:
    return AiderBackend(aider_model="gemini/gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aider_is_available() -> None:
    backend = _make_backend()
    assert await backend.is_available() is True


@pytest.mark.asyncio
async def test_aider_run_returns_success_on_valid_task(tmp_path: Path) -> None:
    """Run aider against a real (temporary) working directory.

    We ask it to describe the file rather than modify it (--dry-run via
    read_only=True) so the test does not require a valid Gemini API key
    to actually apply edits.  What we verify is that aider ran, produced
    output, and exited cleanly.
    """
    _write_buggy_file(tmp_path)
    # Initialise a bare git repo so aider doesn't complain about missing VCS.
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=False, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=False, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com",
             "PATH": shutil.which("git") and str(Path(shutil.which("git")).parent) or ""},
    )

    task = CodingTask(
        intent="code_review",
        description="Briefly describe what buggy.py does — one sentence.",
        workdir=tmp_path,
        files=[Path("buggy.py")],
        read_only=True,
    )
    backend = _make_backend()
    chunks: list[str] = []
    result = await backend.run(task, on_chunk=chunks.append)

    assert result.success is True, f"aider failed:\n{result.error}"
    assert len(chunks) > 0, "Expected at least one line of output from aider"


@pytest.mark.asyncio
async def test_aider_run_produces_output_chunks(tmp_path: Path) -> None:
    """Aider should stream at least one output chunk for any task it starts."""
    _write_buggy_file(tmp_path)
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=False, capture_output=True)

    task = CodingTask(
        intent="code_review",
        description="List the functions defined in buggy.py.",
        workdir=tmp_path,
        files=[Path("buggy.py")],
        read_only=True,
    )
    backend = _make_backend()
    chunks: list[str] = []
    result = await backend.run(task, on_chunk=chunks.append)

    # Whether or not aider can reach its model, it must produce at least some
    # startup / status output before exiting.
    assert len(chunks) > 0, "Expected aider to emit at least one output line"
    # CodingResult must be well-formed regardless of exit code.
    assert isinstance(result.success, bool)
