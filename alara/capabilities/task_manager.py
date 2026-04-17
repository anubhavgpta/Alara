"""Task manager capability — routes task intents and /task slash commands."""

import logging
from pathlib import Path

from rich import print as rich_print

from alara.core.session import SessionContext
from alara.security.permissions import confirm_action
from alara.tasks.display import render_task_list, render_task_result
from alara.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".alara" / "alara.db"

_task_queue: TaskQueue | None = None


def _get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue(_DEFAULT_DB_PATH)
    return _task_queue


def _parse_task_id(user_input: str) -> int | None:
    for token in user_input.split():
        if token.isdigit():
            return int(token)
    return None


async def handle(
    intent: str,
    user_input: str,
    session: SessionContext,
    task_queue: TaskQueue,
) -> None:
    if intent == "research_submit":
        if not confirm_action("Submit background research task?"):
            rich_print("[dim]Cancelled.[/dim]")
            return
        keywords = {"research", "submit", "background", "task", "run", "start"}
        description = " ".join(
            w for w in user_input.split() if w.lower() not in keywords
        ).strip() or user_input
        task = task_queue.submit(description, session.session_id)
        rich_print(f"[green]Task {task.id} submitted.[/green] Check status with /task status")

    elif intent == "research_status":
        tasks = task_queue.list_all(session.session_id)
        if not tasks:
            rich_print("[dim]No background tasks for this session.[/dim]")
        else:
            render_task_list(tasks)

    elif intent == "research_fetch":
        task_id = _parse_task_id(user_input)
        if task_id is None:
            rich_print("[red]Could not parse a task ID from input.[/red]")
            return
        task = task_queue.status(task_id)
        render_task_result(task)

    elif intent == "research_cancel":
        task_id = _parse_task_id(user_input)
        if task_id is None:
            rich_print("[red]Could not parse a task ID from input.[/red]")
            return
        if not confirm_action(f"Cancel task {task_id}?"):
            rich_print("[dim]Cancelled.[/dim]")
            return
        cancelled = task_queue.cancel(task_id)
        if cancelled:
            rich_print(f"[yellow]Task {task_id} cancelled.[/yellow]")
        else:
            rich_print(f"[dim]Task {task_id} could not be cancelled (already running or terminal).[/dim]")

    else:
        logger.warning("task_manager.handle received unknown intent: %s", intent)


async def handle_slash(user_input: str, session: SessionContext) -> None:
    # Strip leading "/task" prefix and normalise whitespace.
    parts = user_input.strip().split()
    # parts[0] is "/task"; subcommand is parts[1] if present
    if len(parts) < 2:
        rich_print("[dim]Usage: /task <submit|status|get|cancel> [args][/dim]")
        return

    subcommand = parts[1].lower()
    rest = " ".join(parts[2:])
    queue = session.task_queue if session.task_queue is not None else _get_task_queue()

    if subcommand == "submit":
        await handle("research_submit", rest, session, queue)
    elif subcommand == "status":
        await handle("research_status", rest, session, queue)
    elif subcommand == "get":
        await handle("research_fetch", rest, session, queue)
    elif subcommand == "cancel":
        await handle("research_cancel", rest, session, queue)
    else:
        logger.warning("Unrecognised /task subcommand: %s", subcommand)
        rich_print(f"[red]Unknown subcommand '{subcommand}'.[/red] Use: submit, status, get, cancel")
