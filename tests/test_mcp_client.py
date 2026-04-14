import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from alara.mcp.client import ComposioMCPClient
from alara.core.errors import AlaraMCPError

@pytest.fixture
def client():
    return ComposioMCPClient(mcp_url="https://fake.composio.dev/mcp", api_key="test-key")

@pytest.mark.asyncio
async def test_call_tool_readonly_no_confirm(client):
    client._session = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text='{"emails": []}')]
    mock_result.isError = False
    client._session.call_tool.return_value = mock_result
    with patch("alara.mcp.client.permissions.confirm_action") as mock_confirm:
        await client.call_tool("GMAIL_FETCH_EMAILS", {"max_results": 5})
        mock_confirm.assert_not_called()

@pytest.mark.asyncio
async def test_call_tool_destructive_triggers_confirm(client):
    client._session = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text="{}")]
    mock_result.isError = False
    client._session.call_tool.return_value = mock_result
    with patch("alara.mcp.client.permissions.confirm_action", return_value=True) as mock_confirm:
        await client.call_tool("GMAIL_SEND_EMAIL", {"to": "a@b.com", "subject": "Hi"})
        mock_confirm.assert_called_once()

@pytest.mark.asyncio
async def test_call_tool_raises_alara_mcp_error_on_failure(client):
    client._session = AsyncMock()
    client._session.call_tool.side_effect = Exception("network error")
    with pytest.raises(AlaraMCPError):
        await client.call_tool("GMAIL_FETCH_EMAILS", {})
