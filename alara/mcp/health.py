"""Startup health check — connects to Composio and reports per-toolkit status."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alara.mcp import composio_setup
from alara.mcp.client import ComposioMCPClient

if TYPE_CHECKING:
    from alara.coding.base import CodingBackend

logger = logging.getLogger(__name__)


@dataclass
class ToolkitStatus:
    """Auth and availability status for one Composio toolkit or coding backend."""

    name: str
    connected: bool   # True = Composio has an active auth connection for this toolkit
    tool_count: int
    error: str | None


async def check_all(
    mcp_client: ComposioMCPClient,
    api_key: str,
    user_id: str,
    configured_toolkits: list[str],
    coding_backend: CodingBackend | None = None,
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
        coding_backend:       Optional coding backend to health-check.  When
                              provided a ToolkitStatus entry is appended.
                              An unavailable backend is non-fatal.

    Returns:
        List of ToolkitStatus, one per configured toolkit plus one for the
        coding backend when coding_backend is not None.
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

    # --- Coding backend health check (non-fatal) ---
    if coding_backend is not None:
        backend_label = type(coding_backend).__name__.replace("Backend", "").lower()
        try:
            available = await coding_backend.is_available()
            statuses.append(
                ToolkitStatus(
                    name=f"Coding ({backend_label})",
                    connected=available,
                    tool_count=0,
                    error=None if available else (
                        f"{backend_label} not found — install it to enable coding features"
                    ),
                )
            )
            logger.debug("Health: coding backend=%s available=%s", backend_label, available)
        except Exception as exc:
            logger.warning("Coding backend health check failed: %s", exc)
            statuses.append(
                ToolkitStatus(
                    name=f"Coding ({backend_label})",
                    connected=False,
                    tool_count=0,
                    error=str(exc)[:80],
                )
            )

    return statuses
