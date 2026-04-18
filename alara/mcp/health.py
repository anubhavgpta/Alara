"""Startup health check — connects to Composio and reports per-toolkit status."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich import print as rich_print
from rich.table import Table

from alara.mcp import composio_setup
from alara.mcp.client import ComposioMCPClient

if TYPE_CHECKING:
    from alara.coding.base import CodingBackend
    from alara.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)


@dataclass
class ToolkitStatus:
    """Auth and availability status for one Composio toolkit or coding backend."""

    name: str
    connected: bool   # True = Composio has an active auth connection for this toolkit
    tool_count: int
    error: str | None


def render_health_table(statuses: list[ToolkitStatus]) -> None:
    """Render per-service health as a Rich table to stdout."""
    if not statuses:
        rich_print("[dim]No health data available.[/dim]")
        return
    table = Table(title="Composio Toolkit Status", show_header=True, header_style="bold")
    table.add_column("Toolkit", style="cyan", min_width=14)
    table.add_column("Status", min_width=12)
    table.add_column("Tools", justify="right", min_width=6)
    table.add_column("Auth", min_width=36)

    for s in statuses:
        if s.error:
            status_str = "[red]unavailable[/red]"
            auth_str = f"[red]{s.error[:50]}[/red]"
        elif s.connected:
            status_str = "[green]ready[/green]"
            auth_str = "[green]authed[/green]"
        else:
            status_str = "[yellow]needs auth[/yellow]"
            auth_str = f"[yellow]run: composio add {s.name}[/yellow]"

        table.add_row(s.name, status_str, str(s.tool_count), auth_str)

    rich_print(table)


async def check_all(
    mcp_client: ComposioMCPClient,
    api_key: str,
    user_id: str,
    configured_toolkits: list[str],
    coding_backend: CodingBackend | None = None,
    task_queue: TaskQueue | None = None,
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
                        f"{backend_label} not found - install it to enable coding features"
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

    # --- Gmail health check ---
    # The per-toolkit loop above already adds a row when "gmail" is in
    # configured_toolkits.  Only add a separate "Gmail" row when gmail is not
    # configured (e.g. Composio unavailable or toolkit not selected), so the
    # user always sees a Gmail status without duplicating it.
    _gmail_already_shown = any("gmail" in s.name.lower() for s in statuses)
    if not _gmail_already_shown:
        if mcp_client is None:
            statuses.append(
                ToolkitStatus(
                    name="Gmail",
                    connected=False,
                    tool_count=0,
                    error="MCP client not initialised",
                )
            )
        else:
            try:
                all_tools = await mcp_client.list_tools()
                gmail_tools = [t for t in all_tools if "GMAIL" in t["name"].upper()]
                if gmail_tools:
                    statuses.append(
                        ToolkitStatus(
                            name="Gmail",
                            connected=True,
                            tool_count=len(gmail_tools),
                            error=None,
                        )
                    )
                    logger.debug("Health: Gmail ready (%d tools)", len(gmail_tools))
                else:
                    statuses.append(
                        ToolkitStatus(
                            name="Gmail",
                            connected=False,
                            tool_count=0,
                            error="Gmail not authenticated",
                        )
                    )
                    logger.debug("Health: Gmail not authenticated")
            except Exception as exc:
                logger.warning("Gmail health check failed: %s", exc)
                statuses.append(
                    ToolkitStatus(
                        name="Gmail",
                        connected=False,
                        tool_count=0,
                        error=str(exc)[:80],
                    )
                )

    # --- Task queue health check ---
    if task_queue is None:
        statuses.append(
            ToolkitStatus(
                name="Task Queue",
                connected=False,
                tool_count=0,
                error="Task queue not initialised",
            )
        )
    else:
        executor = task_queue._executor
        running = executor is not None and not getattr(executor, "_shutdown", True)
        statuses.append(
            ToolkitStatus(
                name="Task Queue",
                connected=running,
                tool_count=0,
                error=None if running else "Task queue executor is shut down",
            )
        )
        logger.debug("Health: task_queue running=%s", running)

    return statuses
