"""Tests for L2 coding routing in alara.core.dispatch."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alara.core.dispatch import CODING_INTENTS, dispatch
from alara.core.session import SessionContext, empty_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_gemini(response: str = "Gemini response") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = response
    return client


def _make_session(tmp_path: Path) -> SessionContext:
    return SessionContext(
        composio_mcp_url="",
        active_toolkits=[],
        available_tools=[],
        active_tools=[],
        started_at=datetime.utcnow(),
        coding_workdir=tmp_path,
        coding_backend="aider",
    )


def _base_config() -> dict:
    return {
        "coding": {
            "backend": "aider",
            "aider_model": "gemini/gemini-2.5-flash",
            "openhands_base_url": "http://localhost:3000",
            "openhands_timeout_seconds": 30,
        }
    }


# ---------------------------------------------------------------------------
# CODING_INTENTS constant
# ---------------------------------------------------------------------------


def test_coding_intents_constant_has_all_five() -> None:
    assert CODING_INTENTS == {
        "code_edit",
        "code_create",
        "code_shell",
        "code_git",
        "code_review",
    }


# ---------------------------------------------------------------------------
# /code slash command routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_slash_command_routes_to_coding_handle(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        result = await dispatch(
            intent={"intent": "chat", "params": {}},
            message="/code fix the login bug",
            client=_mock_gemini(),
            config=_base_config(),
            session_ctx=session,
        )
    mock_handle.assert_called_once()
    assert result == ""


@pytest.mark.asyncio
async def test_code_slash_command_passes_code_edit_intent(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        await dispatch(
            intent={"intent": "chat", "params": {}},
            message="/code fix the login bug",
            client=_mock_gemini(),
            config=_base_config(),
            session_ctx=session,
        )
    assert mock_handle.call_args.args[0] == "code_edit"


@pytest.mark.asyncio
async def test_code_slash_command_strips_prefix_from_description(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        await dispatch(
            intent={"intent": "chat", "params": {}},
            message="/code   refactor the auth module",
            client=_mock_gemini(),
            config=_base_config(),
            session_ctx=session,
        )
    assert mock_handle.call_args.args[1] == "refactor the auth module"


@pytest.mark.asyncio
async def test_code_slash_command_without_session_returns_error_string() -> None:
    result = await dispatch(
        intent={"intent": "chat", "params": {}},
        message="/code fix bug",
        client=_mock_gemini(),
        config=_base_config(),
        session_ctx=None,
    )
    assert "session" in result.lower() or "restart" in result.lower()


# ---------------------------------------------------------------------------
# CODING_INTENTS routing via intent classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_name", list(CODING_INTENTS))
async def test_coding_intent_routes_to_coding_handle(
    intent_name: str, tmp_path: Path
) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        result = await dispatch(
            intent={"intent": intent_name, "params": {}},
            message="do something with code",
            client=_mock_gemini(),
            config=_base_config(),
            session_ctx=session,
        )
    mock_handle.assert_called_once()
    assert result == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_name", list(CODING_INTENTS))
async def test_coding_intent_passes_correct_intent_name(
    intent_name: str, tmp_path: Path
) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        await dispatch(
            intent={"intent": intent_name, "params": {}},
            message="do something with code",
            client=_mock_gemini(),
            config=_base_config(),
            session_ctx=session,
        )
    assert mock_handle.call_args.args[0] == intent_name


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_name", list(CODING_INTENTS))
async def test_coding_intent_without_session_returns_error_string(
    intent_name: str,
) -> None:
    result = await dispatch(
        intent={"intent": intent_name, "params": {}},
        message="do something with code",
        client=_mock_gemini(),
        config=_base_config(),
        session_ctx=None,
    )
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Non-coding intents still route to their own handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_intent_does_not_call_coding_handle(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        with patch("alara.core.dispatch.research.research", return_value="answer"):
            await dispatch(
                intent={"intent": "research", "params": {"query": "Python"}},
                message="explain Python",
                client=_mock_gemini(),
                config=_base_config(),
                session_ctx=session,
            )
    mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_chat_intent_does_not_call_coding_handle(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        await dispatch(
            intent={"intent": "chat", "params": {}},
            message="hello",
            client=_mock_gemini("Hi there!"),
            config=_base_config(),
            session_ctx=session,
        )
    mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# Slash command does not interfere with non-/code messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_code_slash_does_not_route_to_coding(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    with patch("alara.core.dispatch.coding.handle", new_callable=AsyncMock) as mock_handle:
        with patch("alara.core.dispatch.files.list_files", return_value="files"):
            await dispatch(
                intent={"intent": "file_list", "params": {}},
                message="/list my files",
                client=_mock_gemini(),
                config=_base_config(),
                session_ctx=session,
            )
    mock_handle.assert_not_called()
