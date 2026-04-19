"""Route intents to the appropriate capability or Composio tool call."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from io import StringIO
from typing import TYPE_CHECKING

from rich import box as rich_box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from alara.capabilities import coding, files, research, writing
from alara.core.errors import AlaraError, AlaraMCPError
from alara.core.gemini import GeminiClient

if TYPE_CHECKING:
    from alara.core.session import SessionContext
    from alara.mcp.client import ComposioMCPClient
    from alara.mcp.registry import MCPRegistry

logger = logging.getLogger(__name__)

# External intents routed to Composio.
_EXTERNAL_INTENTS: frozenset[str] = frozenset(
    {
        "comms_list", "comms_read", "comms_send", "comms_search",
        "calendar_list", "calendar_create",
        "task_list", "task_create",
    }
)

# L2 coding intents handled by the coding agent.
CODING_INTENTS: frozenset[str] = frozenset(
    {"code_edit", "code_create", "code_shell", "code_git", "code_review"}
)

# Fallback args applied when Gemini arg-extraction fails or returns nothing.
# Ensures list-type tools always get a sensible limit rather than calling with {}.
_TOOL_ARG_DEFAULTS: dict[str, dict] = {
    "GMAIL_FETCH_EMAILS":   {"max_results": 10},
    "GMAIL_LIST_DRAFTS":    {"max_results": 10},
    "GMAIL_LIST_THREADS":   {"max_results": 10},
    "GMAIL_LIST_LABELS":    {},
    "GMAIL_GET_PROFILE":    {},
}

# label_ids filter in GMAIL_FETCH_EMAILS is broken in Composio — passing it
# causes the API to return {}.  Convert any label_ids to an equivalent Gmail
# search query instead (e.g. ["INBOX", "UNREAD"] → "label:INBOX label:UNREAD").
_LABEL_TO_QUERY = {
    "INBOX":                "in:inbox",
    "UNREAD":               "is:unread",
    "STARRED":              "is:starred",
    "IMPORTANT":            "is:important",
    "SPAM":                 "in:spam",
    "TRASH":                "in:trash",
    "SENT":                 "in:sent",
    "CATEGORY_PROMOTIONS":  "category:promotions",
    "CATEGORY_SOCIAL":      "category:social",
    "CATEGORY_UPDATES":     "category:updates",
    "CATEGORY_FORUMS":      "category:forums",
}

_TOOL_SELECT_PROMPT = """\
Select the single best tool to fulfil the user's request from the list below.

Intent classification: {intent}
User request: {query}

Available tools:
{tools}

Reply with ONLY the exact tool name (e.g. GMAIL_FETCH_EMAILS). Reply NONE if no tool fits.
Do not include any explanation or punctuation — just the tool name.
"""

_ARG_EXTRACT_PROMPT = """\
Extract the arguments for the Composio tool '{tool_name}'.
The tool's input schema is: {schema}

User request: {query}

Rules:
- Respond ONLY with a valid JSON object whose keys match the schema properties.
- Do not include markdown fences or any other text.
- For list/fetch operations, always include a sensible default for any limit or \
max_results parameter (use 10 if not specified by the user).
- Omit optional parameters not mentioned or inferable from the request.
"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_json_fences(text: str) -> str:
    match = _JSON_FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def _tool_short_name(tool_name: str) -> str:
    """Derive a short human-readable action name from a tool slug.

    Examples:
        "GMAIL_FETCH_EMAILS"  -> "Fetch emails"
        "GOOGLECALENDAR_CREATE_EVENT" -> "Create event"
        "YOUTUBE" -> "Youtube"
    """
    parts = tool_name.split("_", 1)
    if len(parts) < 2:
        return tool_name.title()
    return parts[1].replace("_", " ").lower().capitalize()


def _select_tool(
    intent: str,
    query: str,
    tools: list[dict],
    client: GeminiClient,
) -> str | None:
    """Use Gemini to pick the best tool for *intent* + *query* from *tools*.

    Falls back to None on any failure so the caller can surface a clean error
    rather than crashing.  The keyword-based registry.find_tool() is a coarser
    alternative that misses semantic synonyms (e.g. "inbox" → GMAIL_FETCH_EMAILS),
    so we delegate to Gemini here.

    Args:
        intent: Classified intent string (e.g. "comms_list").
        query:  Original user message.
        tools:  List of tool dicts with "name" and "description" keys.
        client: GeminiClient instance for the selection call.
    """
    valid_names = {t["name"] for t in tools}
    tool_lines = "\n".join(
        f"- {t['name']}: {(t.get('description') or '')[:100]}"
        for t in tools
    )
    prompt = _TOOL_SELECT_PROMPT.format(intent=intent, query=query, tools=tool_lines)
    try:
        raw = client.chat(prompt, history=[]).strip().strip(".,!? ")
        if not raw or raw.upper() == "NONE":
            return None
        if raw in valid_names:
            return raw
        # Gemini may include extra text — try extracting the last all-caps token
        for token in reversed(raw.split()):
            token = token.strip(".,!? ")
            if token in valid_names:
                return token
        logger.warning("_select_tool: Gemini returned unrecognised name %r", raw)
        return None
    except Exception as exc:
        logger.warning("_select_tool failed: %s", exc)
        return None


def _render_table(table: Table) -> str:
    """Render a Rich Table to a plain string without ANSI codes."""
    sio = StringIO()
    Console(file=sio, no_color=True, width=100).print(table)
    return sio.getvalue().rstrip()


# Zero-width and invisible Unicode characters emitted by HTML email trackers.
_INVISIBLE_CHARS_RE = re.compile(
    r"[\u034f\u00ad\u200b\u200c\u200d\u200e\u200f\u2007\ufeff]+"
)


def _clean_email_text(text: str) -> str:
    """Strip invisible chars and normalise whitespace from email body text."""
    text = _INVISIBLE_CHARS_RE.sub("", text or "")
    text = text.replace("\u00a0", " ").replace("\r\n", " ").replace("\n", " ")
    return re.sub(r" {2,}", " ", text).strip()


def _fmt_timestamp(ts: str) -> str:
    """Format an ISO-8601 UTC timestamp as 'Apr 14, 11:57'."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return ts[:10] if ts else ""


def _sender_display(sender: str) -> str:
    """Extract the display name from 'Name <addr>' or truncate bare address."""
    m = re.match(r"^(.+?)\s*<", sender)
    if m:
        return m.group(1).strip()
    return sender[:22]


_LINE_WIDTH = 98


def _format_email_list(messages: list[dict]) -> str:
    """Render a list of Gmail message dicts as a clean terminal list.

    Each email occupies two lines:
      Line 1: index  unread-dot  sender (padded)  date
      Line 2:        subject
    Zero-width tracker characters are stripped; long text is truncated.
    """
    divider = "─" * _LINE_WIDTH
    lines: list[str] = [divider]

    for i, msg in enumerate(messages, 1):
        unread = "UNREAD" in msg.get("labelIds", [])
        sender = _sender_display(msg.get("sender", ""))[:22]
        subject = _clean_email_text(msg.get("subject", ""))
        date = _fmt_timestamp(msg.get("messageTimestamp", ""))
        preview = _clean_email_text(
            msg.get("preview", {}).get("body", "") or msg.get("messageText", "")
        )

        dot = "●" if unread else " "

        # Line 1: "  1  ●  Sender Name ............  Apr 14, 11:57"
        idx = f"{i:>2}"
        left = f"  {idx}  {dot}  {sender}"
        right = date
        gap = _LINE_WIDTH - len(left) - len(right)
        if gap < 1:
            gap = 1
        line1 = left + " " * gap + right

        # Line 2: "        Subject text here"
        subject_indent = " " * 9
        subject_max = _LINE_WIDTH - len(subject_indent)
        if len(subject) > subject_max:
            subject = subject[: subject_max - 1] + "…"
        line2 = subject_indent + subject

        # Line 3 (preview snippet, dimmed via plain text indicator)
        preview_indent = " " * 9
        preview_max = _LINE_WIDTH - len(preview_indent)
        if len(preview) > preview_max:
            preview = preview[: preview_max - 1] + "…"
        line3 = preview_indent + preview

        lines.append(line1)
        lines.append(line2)
        lines.append(line3)
        lines.append(divider)

    return "\n".join(lines)


async def _dispatch_external(
    intent_name: str,
    message: str,
    client: GeminiClient,
    session_ctx: SessionContext,
    registry: MCPRegistry,
    mcp_client: ComposioMCPClient,
) -> str:
    """Resolve, extract args for, and call a Composio tool."""
    if not session_ctx.active_toolkits:
        return "No external services are active this session."

    tool_name = _select_tool(intent_name, message, session_ctx.active_tools, client)
    if not tool_name:
        toolkit_list = ", ".join(session_ctx.active_toolkits)
        return (
            f"I could not find a suitable tool for that in your active services: {toolkit_list}."
        )

    # Get input schema for the resolved tool.
    tool_schema: dict = {}
    for tool in session_ctx.active_tools:
        if tool["name"] == tool_name:
            tool_schema = tool.get("inputSchema", {})
            break

    # Use Gemini to extract structured args from the natural-language query.
    extract_prompt = _ARG_EXTRACT_PROMPT.format(
        tool_name=tool_name,
        schema=json.dumps(tool_schema),
        query=message,
    )
    args: dict = {}
    try:
        raw = client.chat(extract_prompt, history=[])
        args = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning("Arg extraction JSON parse failed for %s: %s", tool_name, exc)
    except Exception as exc:
        logger.warning("Arg extraction failed for %s: %s", tool_name, exc)

    # Apply per-tool defaults for any keys missing from extracted args.
    # This ensures list tools always get a sane limit even when extraction
    # fails (e.g. Gemini 503 during the extraction call).
    defaults = _TOOL_ARG_DEFAULTS.get(tool_name, {})
    for k, v in defaults.items():
        args.setdefault(k, v)

    # GMAIL_FETCH_EMAILS: label_ids filter is broken in Composio (returns {}).
    # Convert any extracted label_ids to an equivalent Gmail search query term.
    if tool_name == "GMAIL_FETCH_EMAILS" and args.get("label_ids"):
        labels: list = args.pop("label_ids")
        query_parts = [_LABEL_TO_QUERY.get(lbl.upper(), f"label:{lbl}") for lbl in labels]
        existing_query = args.get("query", "").strip()
        combined = " ".join(filter(None, [existing_query] + query_parts))
        if combined:
            args["query"] = combined

    logger.debug("dispatch: tool=%s args=%s", tool_name, args)

    # Execute via the router meta-tool (destructive ops gated inside execute_tool).
    try:
        result = await mcp_client.execute_tool(tool_name, args)
    except AlaraMCPError as exc:
        return str(exc)

    content = result.get("content", [])
    if result.get("status") == "error":
        return f"Tool call failed: {' '.join(content)}"

    # Parse result and render in the most readable form available.
    combined = "\n".join(content)
    try:
        parsed = json.loads(combined)
    except (json.JSONDecodeError, TypeError):
        return combined if combined else "Action completed."

    # Gmail message list
    if isinstance(parsed, dict) and "messages" in parsed:
        msgs = [m for m in parsed["messages"] if isinstance(m, dict)]
        if msgs:
            count = parsed.get("resultSizeEstimate", "")
            header = f"Showing {len(msgs)} of {count} emails:\n" if count else ""
            return header + _format_email_list(msgs)
        # messages key present but empty list
        return "No emails found."

    # Gmail send / create confirmation
    # Shape: {"id": "...", "threadId": "...", "labelIds": ["SENT", ...], "display_url": "..."}
    if (
        isinstance(parsed, dict)
        and "id" in parsed
        and "threadId" in parsed
        and "SENT" in parsed.get("labelIds", [])
    ):
        msg_id = parsed["id"]
        url = parsed.get("display_url", "")
        url_line = f"\n  {url}" if url else ""
        return f"Email sent. (Message ID: {msg_id}){url_line}"

    # Empty dict — tool returned nothing useful
    if parsed == {} or parsed is None:
        return "Action completed."

    # Generic list of dicts → table
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        table = Table(show_header=True, header_style="bold")
        for col in parsed[0].keys():
            table.add_column(str(col), overflow="fold")
        for row in parsed[:20]:
            table.add_row(*[str(v) for v in row.values()])
        return _render_table(table)

    return json.dumps(parsed, indent=2)


async def dispatch(
    intent: dict,
    message: str,
    client: GeminiClient,
    config: dict,
    session_ctx: SessionContext | None = None,
    registry: MCPRegistry | None = None,
    mcp_client: ComposioMCPClient | None = None,
) -> str:
    """Route an intent to the matching capability and return a response string.

    L0 core capabilities (research, files, writing, chat) are handled
    synchronously.  L1 external intents are dispatched via Composio and
    awaited asynchronously.

    Never raises to the REPL — all exceptions are caught and returned as
    user-friendly strings.

    Args:
        intent:      {"intent": str, "params": dict}
        message:     Original user message.
        client:      GeminiClient instance.
        config:      Loaded alara.toml dict.
        session_ctx: Current SessionContext, or None if Composio unavailable.
        registry:    MCPRegistry, or None if Composio unavailable.
        mcp_client:  ComposioMCPClient, or None if Composio unavailable.
    """
    intent_name = intent.get("intent", "chat")
    params = intent.get("params", {})

    try:
        # ----------------------------------------------------------------
        # /tools [service] — services overview or per-service drill-down
        # ----------------------------------------------------------------
        if message.strip() == "/tools" or message.strip().lower().startswith("/tools "):
            from rich import print as rprint
            from rich.table import Table as RichTable
            if session_ctx is None or session_ctx.service_registry is None:
                rprint("[yellow]No service registry available. Run /refresh first.[/yellow]")
                return ""
            _registry = session_ctx.service_registry
            _parts = message.strip().split(None, 1)
            _svc_filter = _parts[1].strip().lower() if len(_parts) == 2 else ""

            if _svc_filter:
                # Drill-down: all tools for one service
                if _svc_filter not in _registry.services:
                    rprint(
                        f"[yellow]Service '{_svc_filter}' not found. "
                        "Run /tools to see available services.[/yellow]"
                    )
                    return ""
                _svc_tools = list(_registry.services[_svc_filter].values())
                tbl = RichTable(
                    title=f"{_svc_filter.title()} Tools",
                    show_header=True,
                    header_style="bold",
                )
                tbl.add_column("Tool", style="bold", min_width=30)
                tbl.add_column("Description", min_width=50)
                tbl.add_column("Destructive", min_width=11)
                for _m in _svc_tools:
                    _dest = "[red]Yes[/red]" if _m.is_destructive else "[green]No[/green]"
                    tbl.add_row(_m.name, _m.description[:80], _dest)
                rprint(tbl)
            else:
                # Top-level: one row per service
                if not _registry.services:
                    rprint("[yellow]No services discovered. Run /refresh to discover services.[/yellow]")
                    return ""
                tbl = RichTable(
                    title="Connected Services",
                    show_header=True,
                    header_style="bold",
                )
                tbl.add_column("Service", style="cyan", min_width=16)
                tbl.add_column("Connected", min_width=9)
                tbl.add_column("Tools", justify="right", min_width=5)
                tbl.add_column("Sample Actions", min_width=40)
                for _svc_name, _tools_dict in sorted(_registry.services.items()):
                    _manifests = list(_tools_dict.values())
                    _count = len(_manifests)
                    _samples = [_tool_short_name(_m.name) for _m in _manifests[:3]]
                    _sample_str = ", ".join(_samples)
                    if _count > 3:
                        _sample_str += "..."
                    tbl.add_row(
                        _svc_name.title(),
                        "[green]Yes[/green]",
                        str(_count),
                        _sample_str,
                    )
                rprint(tbl)
            return ""

        # ----------------------------------------------------------------
        # /use <service> <tool_name> <natural language params>
        # ----------------------------------------------------------------
        if message.strip().startswith("/use "):
            from rich import print as rprint
            parts = message.strip().split(None, 3)
            if len(parts) < 4:
                rprint("[yellow]Usage: /use <service> <tool_name> <natural language params>[/yellow]")
                return ""
            _tool_name = parts[2]
            _nl_params = parts[3]
            from alara.capabilities.generic_mcp import handle as mcp_handle
            await mcp_handle(_tool_name, _nl_params, session_ctx)
            return ""

        # ----------------------------------------------------------------
        # /refresh — rediscover MCP services
        # ----------------------------------------------------------------
        if message.strip() == "/refresh":
            from rich import print as rprint
            from alara.mcp.discovery import discover_services
            if session_ctx is None:
                rprint("[yellow]No session context available.[/yellow]")
                return ""
            session_ctx.service_registry = await discover_services(session_ctx)
            rprint("[green]Service registry refreshed.[/green]")
            return ""

        # ----------------------------------------------------------------
        # /memory slash command — bypasses intent classification
        # ----------------------------------------------------------------
        if message.strip().startswith("/memory"):
            parts = message.strip().split()
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "list":
                from alara.capabilities import memory as memory_cap
                await memory_cap.handle("memory_list", message, session_ctx)
                return ""
            elif sub == "forget":
                from alara.capabilities import memory as memory_cap
                await memory_cap.handle("memory_forget", message, session_ctx)
                return ""
            elif sub == "clear":
                from alara.capabilities import memory as memory_cap
                await memory_cap.handle("memory_clear", message, session_ctx)
                return ""
            else:
                from rich import print as rprint
                rprint("[yellow]Usage: /memory list | /memory forget <id> | /memory clear[/yellow]")
                return ""

        # ----------------------------------------------------------------
        # /health slash command — re-display startup health table
        # ----------------------------------------------------------------
        if message.startswith("/health"):
            from alara.mcp.health import render_health_table
            if session_ctx is not None and session_ctx.health_statuses:
                render_health_table(session_ctx.health_statuses)
            else:
                from rich import print as rich_print
                rich_print("[dim]No health data available for this session.[/dim]")
            return ""

        # ----------------------------------------------------------------
        # /task slash command — bypasses intent classification
        # ----------------------------------------------------------------
        if message.startswith("/task"):
            from alara.capabilities import task_manager
            return await task_manager.handle_slash(message, session_ctx)

        # ----------------------------------------------------------------
        # /gmail slash command — bypasses intent classification
        # ----------------------------------------------------------------
        if message.startswith("/gmail"):
            _gmail_sub = message.strip().split()
            _gmail_cmd = _gmail_sub[1].lower() if len(_gmail_sub) > 1 else ""
            _gmail_map: dict[str, str] = {
                "list":   "comms_list",
                "read":   "comms_read",
                "send":   "comms_send",
                "search": "comms_search",
            }
            _gmail_intent = _gmail_map.get(_gmail_cmd)
            if _gmail_intent is None:
                from rich import print as rprint
                rprint("[dim]Usage: /gmail list | read <id> | send | search <query>[/dim]")
                return ""
            if session_ctx is None:
                return "Gmail requires a session context. Please restart Alara."
            from alara.capabilities import comms
            await comms.handle(_gmail_intent, message, session_ctx, session_ctx.mcp_client)
            return ""

        # ----------------------------------------------------------------
        # /code slash command — bypasses intent classification
        # ----------------------------------------------------------------
        if message.startswith("/code"):
            if session_ctx is None:
                return "Coding agent requires a session context. Please restart Alara."
            task_description = message[len("/code"):].strip()
            await coding.handle(
                "code_edit",
                task_description,
                session_ctx,
                client,
                config,
            )
            return ""

        # ----------------------------------------------------------------
        # /plan slash command — bypasses intent classification
        # ----------------------------------------------------------------
        if message.strip().startswith("/plan"):
            goal = message.strip()[len("/plan"):].strip()
            if not goal:
                from rich import print as rprint
                rprint("[yellow]Usage: /plan <goal>[/yellow]")
                return ""
            from alara.agents.planner import create_plan
            from alara.agents.executor import execute_plan
            plan = await create_plan(goal, session_ctx)
            return await execute_plan(plan, session_ctx)

        # ----------------------------------------------------------------
        # L2 coding intents
        # ----------------------------------------------------------------
        if intent_name in CODING_INTENTS:
            if session_ctx is None:
                return "Coding agent requires a session context. Please restart Alara."
            await coding.handle(
                intent_name,
                message,
                session_ctx,
                client,
                config,
            )
            return ""

        # ----------------------------------------------------------------
        # Background task intents
        # ----------------------------------------------------------------
        _TASK_INTENTS = {"research_submit", "research_status", "research_fetch", "research_cancel"}
        if intent_name in _TASK_INTENTS:
            from alara.capabilities import task_manager
            if session_ctx is None:
                return "Task manager requires a session context. Please restart Alara."
            return await task_manager.handle(intent_name, message, session_ctx, session_ctx.task_queue)

        # ----------------------------------------------------------------
        # L0 file intents
        # ----------------------------------------------------------------
        if intent_name == "research":
            return research.research(params.get("query", message), client)

        if intent_name == "file_read":
            return files.read_file(params.get("path", message))

        if intent_name == "file_write":
            path = params.get("path", "")
            if not path:
                return (
                    "File write requested but no path was identified. "
                    "Please specify a file path."
                )
            return files.write_file(path, params.get("content", message))

        if intent_name == "file_list":
            directory = params.get("path", params.get("directory", ""))
            if directory and not any(
                c in directory for c in ("/", "\\", "~", ".")
            ) and ":" not in directory:
                logger.debug(
                    "file_list path %r looks like natural language — defaulting to workspace root",
                    directory,
                )
                directory = ""
            return files.list_files(directory)

        # ----------------------------------------------------------------
        # L0 writing intents
        # ----------------------------------------------------------------
        if intent_name == "write_draft":
            return writing.draft(params.get("prompt", message), client)

        if intent_name == "write_edit":
            instructions = params.get("instructions", "")
            if not instructions:
                return (
                    "Edit requested but no instructions were identified. "
                    "Please describe the changes you want."
                )
            return writing.edit(params.get("original", message), instructions, client)

        # ----------------------------------------------------------------
        # L4 comms intents — handled by comms capability directly
        # ----------------------------------------------------------------
        COMMS_INTENTS: frozenset[str] = frozenset(
            {"comms_list", "comms_read", "comms_send", "comms_search"}
        )
        if intent_name in COMMS_INTENTS:
            if session_ctx is None:
                return "Gmail requires a session context. Please restart Alara."
            from alara.capabilities import comms
            await comms.handle(intent_name, message, session_ctx, session_ctx.mcp_client)
            return ""

        # ----------------------------------------------------------------
        # L1 external intents via Composio
        # ----------------------------------------------------------------
        if intent_name in _EXTERNAL_INTENTS:
            if session_ctx is None or mcp_client is None or registry is None:
                return (
                    "External service tools are not available this session. "
                    "Ensure Composio is configured and re-launch Alara."
                )
            return await _dispatch_external(
                intent_name, message, client, session_ctx, registry, mcp_client
            )

        # ----------------------------------------------------------------
        # L5 memory intents
        # ----------------------------------------------------------------
        if intent_name in ("memory_list", "memory_forget", "memory_clear"):
            from alara.capabilities import memory as memory_cap
            await memory_cap.handle(intent_name, message, session_ctx)
            return ""

        # ----------------------------------------------------------------
        # L6 multi-agent orchestration intents
        # ----------------------------------------------------------------
        if intent_name == "plan_create":
            from alara.agents.planner import create_plan
            from alara.agents.executor import execute_plan
            plan = await create_plan(message, session_ctx)
            await execute_plan(plan, session_ctx)
            return ""

        # ----------------------------------------------------------------
        # L7 generic MCP tool execution
        # ----------------------------------------------------------------
        if intent_name == "generic_mcp" and session_ctx is not None and session_ctx.pending_mcp_tool:
            tool_name = session_ctx.pending_mcp_tool
            session_ctx.pending_mcp_tool = None
            from alara.capabilities.generic_mcp import handle as mcp_handle
            await mcp_handle(tool_name, message, session_ctx)
            return ""

        # ----------------------------------------------------------------
        # Chat / unknown fallback
        # ----------------------------------------------------------------
        logger.debug("Dispatching to chat fallback for intent: %s", intent_name)
        return client.chat(message, history=[])

    except AlaraError as exc:
        logger.warning("Alara error during dispatch for intent '%s': %s", intent_name, exc)
        return str(exc)
    except Exception as exc:
        logger.exception("Unhandled error during dispatch for intent '%s'", intent_name)
        return f"An error occurred while processing your request: {exc}"
