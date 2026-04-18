"""Session state for a single Alara REPL session."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alara.core.gemini import GeminiClient
    from alara.mcp.client import ComposioMCPClient
    from alara.tasks.queue import TaskQueue


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
        coding_workdir:    Working directory persisted across coding turns.
                           None until the user provides one.
        coding_backend:    Name of the active coding backend ("aider" or "openhands").
                           Set from config at startup; None if coding not configured.
    """

    composio_mcp_url: str
    active_toolkits: list[str]
    available_tools: list[dict]
    active_tools: list[dict]
    started_at: datetime
    coding_workdir: Path | None = None
    coding_backend: str | None = None
    session_id: int = 0
    task_queue: TaskQueue | None = None
    health_statuses: list = field(default_factory=list)
    mcp_client: ComposioMCPClient | None = None
    gemini_client: GeminiClient | None = None


def empty_session() -> SessionContext:
    """Return a no-op SessionContext for when Composio is unavailable."""
    return SessionContext(
        composio_mcp_url="",
        active_toolkits=[],
        available_tools=[],
        active_tools=[],
        started_at=datetime.utcnow(),
    )
