"""Watcher capability — handle watch_add/list/remove/pause intents."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from alara.security.permissions import confirm_action
from alara.watchers import store
from alara.watchers.scheduler import parse_natural_schedule, register_watcher

if TYPE_CHECKING:
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """\
Extract watcher details from this request as JSON with keys:
  description (str) — what to monitor or summarise,
  schedule (str)    — natural language schedule,
  tool (str or null) — exact MCP tool name if mentioned, such as GMAIL_FETCH_EMAILS or \
GOOGLECALENDAR_LIST_EVENTS; never a service slug like 'gmail' or 'googlecalendar',
  params (dict or null) — tool parameters if mentioned.
Return ONLY the JSON object, no markdown fences.

Request: {request}
"""


async def handle(intent: str, user_input: str, session: "SessionContext") -> None:
    """Route watch_add/list/remove/pause intents."""
    if intent == "watch_add":
        await _watch_add(user_input, session)
    elif intent == "watch_list":
        await _watch_list(session)
    elif intent == "watch_remove":
        await _watch_remove(user_input, session)
    elif intent == "watch_pause":
        await _watch_pause(user_input, session)
    else:
        rprint(f"[yellow]Unknown watcher intent: {intent}[/yellow]")


async def _watch_add(user_input: str, session: "SessionContext") -> None:
    """Extract watcher config via Gemini, persist, and register in live schedule."""
    if session.gemini_client is None:
        rprint("[red]Gemini client not available — cannot create watcher.[/red]")
        return

    prompt = _EXTRACT_PROMPT.format(request=user_input)
    description = user_input
    schedule_nl = "every day at 9am"
    tool: str | None = None
    params: dict | None = None

    try:
        raw = session.gemini_client.chat(prompt, history=[])
        raw = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        description = data.get("description", user_input) or user_input
        schedule_nl = data.get("schedule", "every day at 9am") or "every day at 9am"
        tool = data.get("tool") or None
        params = data.get("params") or None
    except Exception as exc:
        logger.warning("_watch_add extraction failed: %s", exc)

    if tool and session.service_registry is not None:
        found = any(
            tool in svc_tools
            for svc_tools in session.service_registry.services.values()
        )
        if not found:
            logger.warning(
                "Tool '%s' not found in registry, using Gemini fallback", tool
            )
            tool = None
            params = None

    cron = parse_natural_schedule(schedule_nl, session.gemini_client)
    watcher_id = store.save_watcher(description, cron, tool, params)

    watcher = store.get_watcher(watcher_id)
    if watcher is not None and session.pt_app is not None:
        register_watcher(watcher, session, session.pt_app)

    rprint(
        f"[green]Watcher #{watcher_id} created.[/green] "
        f"Schedule: [cyan]{cron}[/cyan]  Description: {description}"
    )


async def _watch_list(session: "SessionContext") -> None:
    """Display all active watchers as a rich table."""
    watchers = store.get_all_watchers()
    active = [w for w in watchers if w.status != "deleted"]
    if not active:
        rprint("[yellow]No active watchers.[/yellow]")
        return

    table = Table(title="Active Watchers", show_header=True, header_style="bold")
    table.add_column("ID", justify="right", min_width=4)
    table.add_column("Description", min_width=30)
    table.add_column("Schedule", min_width=12)
    table.add_column("Status", min_width=8)
    table.add_column("Last Run", min_width=20)
    table.add_column("Last Result", min_width=30)

    for w in active:
        status_str = (
            "[green]active[/green]" if w.status == "active" else "[yellow]paused[/yellow]"
        )
        table.add_row(
            str(w.id),
            w.description[:50],
            w.schedule,
            status_str,
            w.last_run or "never",
            (w.last_result or "")[:40],
        )
    rprint(table)


async def _watch_remove(user_input: str, session: "SessionContext") -> None:
    """Confirm and delete a watcher by ID."""
    import schedule as sched

    watcher_id = _parse_id(user_input)
    if watcher_id is None:
        rprint("[yellow]Could not parse watcher ID. Usage: /watch remove <id>[/yellow]")
        return

    watcher = store.get_watcher(watcher_id)
    if watcher is None:
        rprint(f"[yellow]Watcher #{watcher_id} not found.[/yellow]")
        return

    if not confirm_action(f"Delete watcher #{watcher_id}: {watcher.description}?"):
        rprint("[yellow]Cancelled.[/yellow]")
        return

    store.delete_watcher(watcher_id)
    sched.clear(f"watcher-{watcher_id}")
    rprint(f"[green]Watcher #{watcher_id} deleted.[/green]")


async def _watch_pause(user_input: str, session: "SessionContext") -> None:
    """Pause a watcher by ID."""
    import schedule as sched

    watcher_id = _parse_id(user_input)
    if watcher_id is None:
        rprint("[yellow]Could not parse watcher ID. Usage: /watch pause <id>[/yellow]")
        return

    watcher = store.get_watcher(watcher_id)
    if watcher is None:
        rprint(f"[yellow]Watcher #{watcher_id} not found.[/yellow]")
        return

    store.pause_watcher(watcher_id)
    sched.clear(f"watcher-{watcher_id}")
    rprint(f"[yellow]Watcher #{watcher_id} paused.[/yellow]")


def _parse_id(text: str) -> int | None:
    """Extract the first integer from text, or None."""
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    return None
