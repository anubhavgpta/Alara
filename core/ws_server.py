"""WebSocket server placeholders for future text-first UI integration."""

from __future__ import annotations

from typing import Any


_ACTIVE_SERVER: "AlaraWSServer | None" = None


def broadcast(message: dict[str, Any]) -> None:
    """Broadcast UI events to connected clients."""
    # TODO: Implement WebSocket broadcast transport.
    pass


class AlaraWSServer:
    """WebSocket bridge placeholder for UI and orchestrator communication."""

    def __init__(self, host: str = "localhost", port: int = 8765) -> None:
        """Initialize server configuration."""
        # TODO: Define message schema and transport lifecycle.
        pass

    def start_background(self) -> None:
        """Start the server in background mode."""
        # TODO: Implement background async event loop startup.
        pass
