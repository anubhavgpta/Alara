"""Startup health check — connects to Composio and reports per-toolkit status."""

import logging
from dataclasses import dataclass

from alara.mcp import composio_setup
from alara.mcp.client import ComposioMCPClient

logger = logging.getLogger(__name__)


@dataclass
class ToolkitStatus:
    """Auth and availability status for one Composio toolkit."""

    name: str
    connected: bool   # True = Composio has an active auth connection for this toolkit
    tool_count: int
    error: str | None


async def check_all(
    mcp_client: ComposioMCPClient,
    api_key: str,
    user_id: str,
    configured_toolkits: list[str],
) -> list[ToolkitStatus]:
    """Return per-toolkit health status for all configured toolkits.

    Steps:
      1. For each toolkit, call composio_setup.get_toolkit_tools() via the
         Composio REST API to get the real tool count.  The MCP list_tools()
         endpoint only returns generic meta-tools (COMPOSIO_GET_TOOL_SCHEMAS,
         etc.), not toolkit-specific actions, so it cannot be used for counts.
      2. Call composio_setup.get_connection_status() to flag OAuth status.

    Args:
        mcp_client:           Connected ComposioMCPClient instance (kept for
                              future use; not used for tool counting here).
        api_key:              Composio API key (for REST API calls).
        user_id:              Composio entity / user identifier.
        configured_toolkits:  Toolkit names from alara.toml [composio].

    Returns:
        List of ToolkitStatus, one per configured toolkit.
    """
    statuses: list[ToolkitStatus] = []
    for toolkit in configured_toolkits:
        tools = composio_setup.get_toolkit_tools(api_key, toolkit)
        tool_count = len(tools)
        connected = composio_setup.get_connection_status(api_key, user_id, toolkit)
        logger.debug(
            "Health: toolkit=%s connected=%s tools=%d",
            toolkit, connected, tool_count,
        )
        statuses.append(
            ToolkitStatus(
                name=toolkit,
                connected=connected,
                tool_count=tool_count,
                error=None,
            )
        )

    return statuses
