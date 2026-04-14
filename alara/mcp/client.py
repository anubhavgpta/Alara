"""MCP client stub for L0.

Full MCP connectivity will be implemented in L1. This stub provides the
interface so that higher-level code can be written against it now.
"""

import logging

logger = logging.getLogger(__name__)


class MCPClient:
    """Minimal MCP client stub.

    Logs tool calls and returns stub responses. Will be replaced with a
    real stdio/SSE transport implementation in L1.
    """

    def __init__(self, server_name: str, transport: str = "stdio") -> None:
        self.server_name = server_name
        self.transport = transport
        logger.info("MCP client initialised for %s (%s)", server_name, transport)

    def call_tool(self, tool_name: str, params: dict) -> dict:
        """Stub tool call — logs a warning and returns a stub response.

        Args:
            tool_name: Name of the MCP tool to call.
            params: Parameters to pass to the tool.

        Returns:
            A dict indicating the stub status.
        """
        logger.warning("MCP tool call stubbed: %s", tool_name)
        return {"status": "stub", "message": "MCP not yet connected"}
