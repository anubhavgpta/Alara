"""Integration test for OpenHandsBackend — requires a running OpenHands server.

Set the environment variable to enable:

  PowerShell:
    $env:ALARA_TEST_OPENHANDS="1"; pytest tests/integration/test_openhands_integration.py -v

  bash / CMD:
    ALARA_TEST_OPENHANDS=1 pytest tests/integration/test_openhands_integration.py -v

Skipped entirely in CI unless the env var is set.
"""

import os
from pathlib import Path

import pytest

from alara.coding.models import CodingTask
from alara.coding.openhands_backend import OpenHandsBackend

pytestmark = pytest.mark.skipif(
    os.environ.get("ALARA_TEST_OPENHANDS") != "1",
    reason="Set ALARA_TEST_OPENHANDS=1 to run OpenHands integration tests",
)

_OPENHANDS_URL = os.environ.get("ALARA_OPENHANDS_URL", "http://localhost:3000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend() -> OpenHandsBackend:
    return OpenHandsBackend(base_url=_OPENHANDS_URL, timeout_seconds=120)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openhands_is_available() -> None:
    backend = _make_backend()
    available = await backend.is_available()
    assert available is True, (
        f"OpenHands server at {_OPENHANDS_URL} is not reachable. "
        "Start it before running this test."
    )


@pytest.mark.asyncio
async def test_openhands_run_read_only_review_task(tmp_path: Path) -> None:
    """Send a read-only review request and verify we receive at least one chunk."""
    backend = _make_backend()
    if not await backend.is_available():
        pytest.skip(
            f"OpenHands server at {_OPENHANDS_URL} is not reachable — start it first."
        )

    (tmp_path / "sample.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}'\n",
        encoding="utf-8",
    )
    task = CodingTask(
        intent="code_review",
        description="Briefly describe what sample.py does in one sentence.",
        workdir=tmp_path,
        files=[Path("sample.py")],
        read_only=True,
    )
    chunks: list[str] = []
    result = await backend.run(task, on_chunk=chunks.append)

    assert result.success is True, f"OpenHands task failed:\n{result.error}"
    # We must have received at least some output from the server.
    assert len(chunks) > 0, "Expected at least one chunk from OpenHands"
    assert any(chunk.strip() for chunk in chunks), "All chunks were empty"
