"""Unit tests for OpenHandsBackend — all HTTP I/O is mocked."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from alara.coding.models import CodingTask
from alara.coding.openhands_backend import OpenHandsBackend
from alara.core.errors import AlaraAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend(
    base_url: str = "http://localhost:3000",
    timeout: int = 30,
) -> OpenHandsBackend:
    return OpenHandsBackend(base_url=base_url, timeout_seconds=timeout)


def _make_task(tmp_path: Path, read_only: bool = False) -> CodingTask:
    return CodingTask(
        intent="code_review" if read_only else "code_edit",
        description="Refactor the auth module",
        workdir=tmp_path,
        read_only=read_only,
    )


def _sse_lines(events: list[dict]) -> list[str]:
    """Format a list of event dicts as raw SSE text lines."""
    lines: list[str] = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")
    return lines


def _make_httpx_client_mock(
    health_status: int = 200,
    conv_id: str = "conv-abc",
    sse_events: list[dict] | None = None,
    health_side_effect: Exception | None = None,
    post_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a layered mock of httpx.AsyncClient for OpenHands tests."""
    if sse_events is None:
        sse_events = [
            {"message": "Starting task", "type": "output"},
            {"message": "Done", "type": "finish"},
        ]

    lines = _sse_lines(sse_events)

    # Async iterator for aiter_lines
    async def _aiter_lines():
        for line in lines:
            yield line

    mock_stream_obj = MagicMock()
    mock_stream_obj.aiter_lines = _aiter_lines

    @asynccontextmanager
    async def _stream_ctx(*args, **kwargs):
        yield mock_stream_obj

    # POST /api/conversations response
    mock_post_resp = MagicMock()
    mock_post_resp.raise_for_status = MagicMock()
    mock_post_resp.json.return_value = {"id": conv_id}

    # GET /health response
    mock_health_resp = MagicMock()
    mock_health_resp.status_code = health_status

    mock_client = AsyncMock()
    if health_side_effect:
        mock_client.get.side_effect = health_side_effect
    else:
        mock_client.get.return_value = mock_health_resp

    if post_side_effect:
        mock_client.post.side_effect = post_side_effect
    else:
        mock_client.post.return_value = mock_post_resp

    mock_client.stream = _stream_ctx
    mock_client.delete = AsyncMock(return_value=MagicMock())

    return mock_client


def _patch_client(mock_client: AsyncMock):
    """Context manager that patches httpx.AsyncClient in the openhands module."""
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return patch("alara.coding.openhands_backend.httpx.AsyncClient", mock_cls)


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_available_returns_true_on_200() -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(health_status=200)
    with _patch_client(mock_client):
        assert await backend.is_available() is True


@pytest.mark.asyncio
async def test_is_available_returns_false_on_connection_error() -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(
        health_side_effect=httpx.ConnectError("refused")
    )
    with _patch_client(mock_client):
        assert await backend.is_available() is False


@pytest.mark.asyncio
async def test_is_available_returns_false_on_timeout() -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(
        health_side_effect=httpx.TimeoutException("timeout")
    )
    with _patch_client(mock_client):
        assert await backend.is_available() is False


@pytest.mark.asyncio
async def test_is_available_returns_false_on_500() -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(health_status=500)
    with _patch_client(mock_client):
        assert await backend.is_available() is False


# ---------------------------------------------------------------------------
# run() — success / chunk streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_success_result(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock()
    with _patch_client(mock_client):
        result = await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)
    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_run_streams_event_messages_via_on_chunk(tmp_path: Path) -> None:
    backend = _make_backend()
    events = [
        {"message": "Analysing files", "type": "output"},
        {"message": "Writing patch", "type": "output"},
        {"message": "Complete", "type": "finish"},
    ]
    mock_client = _make_httpx_client_mock(sse_events=events)

    received: list[str] = []
    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path), on_chunk=received.append)

    assert "Analysing files" in received
    assert "Writing patch" in received
    assert "Complete" in received


@pytest.mark.asyncio
async def test_run_stops_at_finish_event(tmp_path: Path) -> None:
    """Events after the finish marker must not be forwarded."""
    backend = _make_backend()
    events = [
        {"message": "done", "type": "finish"},
        {"message": "should not appear", "type": "output"},
    ]
    mock_client = _make_httpx_client_mock(sse_events=events)

    received: list[str] = []
    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path), on_chunk=received.append)

    assert "should not appear" not in received


@pytest.mark.asyncio
async def test_run_deletes_conversation_after_completion(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(conv_id="conv-xyz")
    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    mock_client.delete.assert_called_once()
    delete_url = mock_client.delete.call_args.args[0]
    assert "conv-xyz" in delete_url


# ---------------------------------------------------------------------------
# run() — read_only flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_appends_no_modify_suffix_for_read_only(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock()

    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path, read_only=True), on_chunk=lambda _: None)

    call_json = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1] if mock_client.post.call_args.args else mock_client.post.call_args.kwargs["json"]
    assert "Do not modify any files." in call_json["initial_message"]


@pytest.mark.asyncio
async def test_run_does_not_append_suffix_for_write_task(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock()

    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path, read_only=False), on_chunk=lambda _: None)

    post_json = mock_client.post.call_args.kwargs.get("json", {})
    assert "Do not modify any files." not in post_json.get("initial_message", "")


# ---------------------------------------------------------------------------
# run() — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_raises_alara_api_error_on_post_http_error(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(
        post_side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
    )
    with _patch_client(mock_client):
        with pytest.raises(AlaraAPIError, match="OpenHands"):
            await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)


@pytest.mark.asyncio
async def test_run_raises_alara_api_error_on_timeout(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock(
        post_side_effect=httpx.TimeoutException("timed out")
    )
    with _patch_client(mock_client):
        with pytest.raises(AlaraAPIError):
            await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)


@pytest.mark.asyncio
async def test_run_includes_workdir_in_post_payload(tmp_path: Path) -> None:
    backend = _make_backend()
    mock_client = _make_httpx_client_mock()

    with _patch_client(mock_client):
        await backend.run(_make_task(tmp_path), on_chunk=lambda _: None)

    post_json = mock_client.post.call_args.kwargs.get("json", {})
    assert str(tmp_path) == post_json.get("repository")
