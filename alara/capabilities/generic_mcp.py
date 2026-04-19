"""Generic MCP tool executor — Gemini-guided parameter extraction and execution."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from rich import print as rprint
from rich.panel import Panel

from alara.memory.extractor import _strip_fences
from alara.security.permissions import confirm_action

if TYPE_CHECKING:
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)


def _log_tool_call(
    session_id: int,
    service: str,
    tool: str,
    params: dict | None,
    status: str,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    try:
        import sqlite3
        from pathlib import Path

        _db_path = Path.home() / ".alara" / "alara.db"
        conn = sqlite3.connect(str(_db_path), check_same_thread=False)
        conn.execute(
            """INSERT INTO mcp_tool_log
               (session_id, service, tool, params, status, error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                service,
                tool,
                json.dumps(params) if params is not None else None,
                status,
                error,
                duration_ms,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("mcp_tool_log write failed: %s", exc)


async def handle(tool_name: str, natural_language: str, session: "SessionContext") -> None:
    """Execute an MCP tool identified by name, using Gemini to extract params."""
    registry = session.service_registry
    if registry is None:
        rprint("[red]No service registry available. Run /refresh to discover services.[/red]")
        return

    manifest = None
    for tools in registry.services.values():
        if tool_name in tools:
            manifest = tools[tool_name]
            break

    if manifest is None:
        rprint(f"[red]Tool '{tool_name}' not found in service registry.[/red]")
        return

    if session.gemini_client is None:
        rprint("[red]Gemini client not available.[/red]")
        return

    extraction_prompt = (
        f"Given this tool input schema: {json.dumps(manifest.input_schema)} "
        "Extract the parameters from the user's request as a JSON object. "
        "Return ONLY a JSON object, no markdown fences, no explanation.\n\n"
        f"User request: {natural_language}"
    )

    try:
        raw = session.gemini_client.chat(extraction_prompt, history=[])
        params = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning("generic_mcp param extraction JSON parse failed: %s", exc)
        rprint(f"[red]Could not parse parameters for tool '{tool_name}': {exc}[/red]")
        return
    except Exception as exc:
        logger.warning("generic_mcp param extraction failed: %s", exc)
        rprint(f"[red]Parameter extraction failed: {exc}[/red]")
        return

    if manifest.is_destructive:
        allowed = confirm_action(f"Run {tool_name} with params: {params}?")
        if not allowed:
            _log_tool_call(
                session.session_id,
                manifest.service,
                tool_name,
                params,
                "cancelled",
            )
            return

    start = time.monotonic()

    try:
        if session.mcp_client is None:
            raise RuntimeError("MCP client not available")
        result = await session.mcp_client.execute_tool(tool_name, params)
        duration_ms = int((time.monotonic() - start) * 1000)

        content = result.get("content", [])
        display = "\n".join(content) if content else "Action completed."
        rprint(Panel(display, title=tool_name))

        _log_tool_call(
            session.session_id,
            manifest.service,
            tool_name,
            params,
            "success",
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            session.session_id,
            manifest.service,
            tool_name,
            params,
            "failed",
            error=str(exc),
            duration_ms=duration_ms,
        )
        raise
