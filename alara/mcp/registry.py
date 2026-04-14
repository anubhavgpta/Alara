"""MCP tool registry — indexes Composio tools for discovery and prompt injection."""

import logging

logger = logging.getLogger(__name__)

_MIN_KEYWORD_LEN = 3
_MAX_TOOLS_IN_PROMPT = 12  # cap per toolkit to keep system prompt concise


class MCPRegistry:
    """Indexes tools returned by ComposioMCPClient.list_tools().

    Typical usage::

        registry = MCPRegistry()
        registry.load(await mcp_client.list_tools())

        tool_name = registry.find_tool("comms_send", "send email to alice", ["gmail"])
        fragment  = registry.get_system_prompt_fragment(["gmail", "slack"])
    """

    def __init__(self) -> None:
        self._tools: list[dict] = []
        # toolkit name -> list of tool dicts belonging to that toolkit
        self._toolkits: dict[str, list[dict]] = {}

    def load(self, tools: list[dict]) -> None:
        """Populate the registry from a flat list of tool dicts.

        Each dict must have at minimum "name" and "toolkit" keys (both strings).
        Clears any previously loaded tools.
        """
        self._tools = tools
        self._toolkits = {}
        for tool in tools:
            tk = tool.get("toolkit", "")
            self._toolkits.setdefault(tk, []).append(tool)
        logger.debug(
            "Registry loaded: %d tools across %d toolkits",
            len(self._tools), len(self._toolkits),
        )

    def available_toolkits(self) -> list[str]:
        """Return a sorted list of all toolkit names present in the registry."""
        return sorted(self._toolkits)

    def tools_for_toolkit(self, toolkit: str) -> list[dict]:
        """Return all tools belonging to *toolkit*, or an empty list."""
        return list(self._toolkits.get(toolkit, []))

    def find_tool(
        self, intent: str, query: str, active_toolkits: list[str]
    ) -> str | None:
        """Return the best-matching tool name for *intent* + *query*.

        Searches only tools belonging to one of the *active_toolkits*.
        Scores by counting how many significant words from the combined search
        string appear in the tool's name or description.  Returns None if no
        tool scores above zero.

        Args:
            intent:          Classified intent string (e.g. "comms_send").
            query:           Original user message or extracted query.
            active_toolkits: Toolkits the user activated this session.
        """
        search_words = {
            w for w in f"{intent} {query}".lower().split()
            if len(w) >= _MIN_KEYWORD_LEN
        }
        if not search_words:
            return None

        # If the query explicitly names a toolkit that is not currently active,
        # bail out rather than returning a weak match from a different toolkit.
        # Example: "send a slack message" with only gmail active → None.
        inactive_toolkits = {tk for tk in self._toolkits if tk not in active_toolkits}
        if any(tk in query.lower() for tk in inactive_toolkits):
            logger.debug(
                "find_tool: query references inactive toolkit — returning None"
            )
            return None

        best_score = 0
        best_name: str | None = None

        for tool in self._tools:
            if tool.get("toolkit") not in active_toolkits:
                continue
            text = f"{tool['name']} {tool.get('description', '')}".lower()
            score = sum(1 for w in search_words if w in text)
            if score > best_score:
                best_score = score
                best_name = tool["name"]

        if best_name:
            logger.debug(
                "find_tool: matched '%s' (score=%d) for intent=%r query=%r",
                best_name, best_score, intent, query,
            )
        return best_name

    def get_system_prompt_fragment(self, active_toolkits: list[str]) -> str:
        """Return a concise plain-text summary of tools for the system prompt.

        Only tools belonging to *active_toolkits* are included.  Each toolkit
        is listed on one line with its available tool names.  Returns an empty
        string when there are no active toolkits.

        Format::

            Available external tools:
            - gmail: GMAIL_FETCH_EMAILS, GMAIL_SEND_EMAIL, GMAIL_SEARCH_EMAILS
            - slack: SLACK_SENDS_A_MESSAGE, SLACK_LIST_CHANNELS
        """
        if not active_toolkits:
            return ""

        lines: list[str] = ["Available external tools:"]
        for toolkit in sorted(active_toolkits):
            tools = self._toolkits.get(toolkit, [])
            if not tools:
                continue
            names = [t["name"] for t in tools[:_MAX_TOOLS_IN_PROMPT]]
            if len(tools) > _MAX_TOOLS_IN_PROMPT:
                names.append(f"... and {len(tools) - _MAX_TOOLS_IN_PROMPT} more")
            lines.append(f"- {toolkit}: {', '.join(names)}")

        return "\n".join(lines) if len(lines) > 1 else ""
