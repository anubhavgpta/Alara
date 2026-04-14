"""Composio MCP client — connects to the Composio Tool Router over streamable HTTP."""

import json
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from alara.core.errors import AlaraMCPError
from alara.security import permissions

logger = logging.getLogger(__name__)

# Tool-name substrings that indicate a write/destructive operation.
_DESTRUCTIVE_KEYWORDS: frozenset[str] = frozenset(
    {"SEND", "DELETE", "CREATE", "UPDATE", "MODIFY"}
)


def _is_destructive(tool_name: str) -> bool:
    upper = tool_name.upper()
    return any(kw in upper for kw in _DESTRUCTIVE_KEYWORDS)


def _toolkit_from_name(name: str) -> str:
    """Parse toolkit prefix from a Composio tool name.

    Examples:
        "GMAIL_FETCH_EMAILS"      -> "gmail"
        "SLACK_SENDS_A_MESSAGE"   -> "slack"
        "unknown"                 -> "unknown"
    """
    return name.split("_")[0].lower() if "_" in name else name.lower()


class ComposioMCPClient:
    """Async MCP client that connects to a Composio Tool Router URL.

    Must be used as an async context manager, or connect/disconnect called
    explicitly:

        async with ComposioMCPClient(url, key) as client:
            tools = await client.list_tools()

    Destructive tools (names containing SEND, DELETE, CREATE, UPDATE, MODIFY)
    are gated through permissions.confirm_action() before execution.
    """

    def __init__(self, mcp_url: str, api_key: str, user_id: str = "") -> None:
        self._mcp_url = mcp_url
        self._api_key = api_key
        self._user_id = user_id
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ComposioMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open an MCP session over streamable HTTP to the Composio Tool Router.

        Raises:
            AlaraMCPError: On transport or initialisation failure.
        """
        if self._session is not None:
            logger.debug("ComposioMCPClient already connected — skipping reconnect")
            return

        stack = AsyncExitStack()
        try:
            streams = await stack.enter_async_context(
                streamablehttp_client(
                    url=self._mcp_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            )
            # streamablehttp_client returns (read, write) or (read, write, get_session_id)
            read, write, *_ = streams

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._session = session
            self._stack = stack
            logger.info("Composio MCP session established")
        except Exception as exc:
            await stack.aclose()
            raise AlaraMCPError(
                f"Failed to connect to Composio Tool Router: {exc}"
            ) from exc

    async def list_tools(self) -> list[dict]:
        """Return all tools available in this Composio session.

        Each tool is a dict with keys: name, description, toolkit, inputSchema.
        Toolkit is parsed from the tool-name prefix (e.g. "GMAIL_" -> "gmail").

        Paginates automatically — follows nextCursor until exhausted so no
        tools are silently truncated on large sessions.

        Raises:
            AlaraMCPError: If not connected or the list call fails.
        """
        self._require_session()
        tools: list[dict] = []
        cursor: str | None = None

        while True:
            try:
                result = await self._session.list_tools(  # type: ignore[union-attr]
                    cursor=cursor
                )
            except Exception as exc:
                raise AlaraMCPError(f"list_tools() failed: {exc}") from exc

            for t in result.tools:
                tools.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "toolkit": _toolkit_from_name(t.name),
                        "inputSchema": (
                            t.inputSchema if hasattr(t, "inputSchema") else {}
                        ),
                    }
                )

            cursor = getattr(result, "nextCursor", None)
            if not cursor:
                break

        logger.info(
            "list_tools returned %d tools total: %s",
            len(tools),
            [t["name"] for t in tools],
        )
        return tools

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Call a Composio tool and return a normalised result dict.

        Destructive operations (SEND, DELETE, CREATE, UPDATE, MODIFY in the
        tool name) are gated through the user permission dialog before the
        API call is made.

        Args:
            tool_name: Composio tool name (e.g. "GMAIL_SEND_EMAIL").
            args:      Arguments matching the tool's inputSchema.

        Returns:
            {"status": "ok"|"error", "content": list[str]}

        Raises:
            AlaraMCPError: If permission denied, not connected, or call fails.
        """
        self._require_session()

        if _is_destructive(tool_name):
            summary = ", ".join(
                f"{k}={str(v)[:40]}" for k, v in list(args.items())[:4]
            )
            gate_msg = f"Tool: {tool_name} | Args: {summary}"
            if not permissions.confirm_action(gate_msg):
                raise AlaraMCPError(f"Tool call '{tool_name}' cancelled by user.")

        logger.debug("Calling tool %s with args keys=%s", tool_name, list(args))
        try:
            result = await self._session.call_tool(tool_name, args)  # type: ignore[union-attr]
        except Exception as exc:
            raise AlaraMCPError(f"Tool call '{tool_name}' failed: {exc}") from exc

        texts: list[str] = []
        for item in result.content:
            if hasattr(item, "text") and item.text:
                texts.append(item.text)

        status = "error" if getattr(result, "isError", False) else "ok"
        logger.debug(
            "Tool %s returned status=%s content_items=%d", tool_name, status, len(texts)
        )
        return {"status": status, "content": texts}

    async def execute_tool(self, tool_slug: str, args: dict) -> dict:
        """Execute a toolkit action (e.g. GMAIL_FETCH_EMAILS) via the router.

        The Composio Tool Router does not expose toolkit-specific tools
        directly via MCP list_tools / call_tool.  All real actions must be
        dispatched through the COMPOSIO_MULTI_EXECUTE_TOOL meta-tool, which
        accepts a list of {tool_slug, arguments} items and returns nested
        results.  This method wraps that protocol and normalises the response
        to the same {"status", "content"} dict that call_tool() returns.

        Destructive tools are gated through the user permission dialog on
        the *inner* tool_slug, not the meta-tool name.

        Args:
            tool_slug: Real toolkit tool name (e.g. "GMAIL_FETCH_EMAILS").
            args:      Arguments matching the tool's inputSchema.

        Returns:
            {"status": "ok"|"error", "content": list[str]}

        Raises:
            AlaraMCPError: If permission denied, not connected, or call fails.
        """
        self._require_session()

        if _is_destructive(tool_slug):
            summary = ", ".join(
                f"{k}={str(v)[:40]}" for k, v in list(args.items())[:4]
            )
            gate_msg = f"Tool: {tool_slug} | Args: {summary}"
            if not permissions.confirm_action(gate_msg):
                raise AlaraMCPError(f"Tool call '{tool_slug}' cancelled by user.")

        # Prefer the ComposioToolSet REST path — it returns the full untruncated
        # response.  The MCP MULTI_EXECUTE_TOOL path only returns data_preview
        # (Composio truncates it to avoid flooding LLM context windows).
        if self._user_id:
            try:
                import anyio
                from alara.mcp import composio_setup
                return await anyio.to_thread.run_sync(
                    lambda: composio_setup.execute_action(
                        self._api_key, self._user_id, tool_slug, args
                    )
                )
            except Exception as exc:
                logger.debug(
                    "execute_tool: REST path failed for %s (%s) — falling back to MCP",
                    tool_slug, exc,
                )

        # MCP fallback via COMPOSIO_MULTI_EXECUTE_TOOL
        logger.debug("Executing toolkit tool %s via MULTI_EXECUTE", tool_slug)
        raw = await self.call_tool(
            "COMPOSIO_MULTI_EXECUTE_TOOL",
            {
                "tools": [{"tool_slug": tool_slug, "arguments": args}],
                "sync_response_to_workbench": False,
            },
        )

        if raw["status"] == "error":
            return raw

        # Unwrap nested response:
        # {successful, data: {results: [{response: {successful, data_preview: {...}}}]}}
        combined = "\n".join(raw["content"])
        try:
            outer = json.loads(combined)
            results = outer.get("data", {}).get("results", [])
            if results:
                inner = results[0].get("response", {})
                inner_ok: bool = inner.get("successful", False)
                inner_data = inner.get("data") or inner.get("data_preview") or {}
                return {
                    "status": "ok" if inner_ok else "error",
                    "content": [json.dumps(inner_data)],
                }
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.debug("execute_tool: could not unwrap MULTI_EXECUTE response")

        return raw

    async def disconnect(self) -> None:
        """Close the MCP session and release the underlying HTTP transport."""
        if self._stack is not None:
            try:
                await self._stack.aclose()
                logger.debug("Composio MCP session closed")
            except Exception as exc:
                logger.warning("Error closing MCP session: %s", exc)
            finally:
                self._stack = None
                self._session = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_session(self) -> None:
        if self._session is None:
            raise AlaraMCPError(
                "ComposioMCPClient is not connected. Call connect() first."
            )
