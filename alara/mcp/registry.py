"""Registry for MCP server clients."""

import logging

from alara.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Maintains a named collection of MCPClient instances."""

    def __init__(self) -> None:
        self.servers: dict[str, MCPClient] = {}

    def register(self, name: str, client: MCPClient) -> None:
        """Register an MCPClient under the given name."""
        self.servers[name] = client
        logger.debug("Registered MCP server: %s", name)

    def list_servers(self) -> list[str]:
        """Return the names of all registered MCP servers."""
        return list(self.servers.keys())

    def get(self, name: str) -> MCPClient | None:
        """Return the MCPClient registered under *name*, or None."""
        return self.servers.get(name)
