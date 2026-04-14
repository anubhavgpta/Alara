"""Session state for a single Alara REPL session."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionContext:
    """Holds all runtime state for one Alara session.

    Attributes:
        composio_mcp_url:  The Composio Tool Router URL for this session.
                           Empty string when Composio is unavailable.
        active_toolkits:   Toolkit names the user selected at session start.
        available_tools:   Full tool list returned by list_tools() this session.
        active_tools:      Subset of available_tools belonging to active_toolkits.
        started_at:        UTC timestamp when the session was created.
    """

    composio_mcp_url: str
    active_toolkits: list[str]
    available_tools: list[dict]
    active_tools: list[dict]
    started_at: datetime


def empty_session() -> SessionContext:
    """Return a no-op SessionContext for when Composio is unavailable."""
    return SessionContext(
        composio_mcp_url="",
        active_toolkits=[],
        available_tools=[],
        active_tools=[],
        started_at=datetime.utcnow(),
    )
