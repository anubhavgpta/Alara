"""Memory capability — list, forget, and clear stored memories."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich import print as rprint
from rich.table import Table

from alara.memory.store import clear_all_memories, forget_memory, get_all_memories
from alara.security.permissions import confirm_action

if TYPE_CHECKING:
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)


async def handle(intent: str, user_input: str, session: SessionContext) -> None:
    if intent == "memory_list":
        memories = get_all_memories()
        if not memories:
            rprint("[yellow]No memories stored.[/yellow]")
            return

        table = Table(title="Stored Memories", show_header=True, header_style="bold")
        table.add_column("#", justify="right", min_width=4)
        table.add_column("Key", min_width=20)
        table.add_column("Value", min_width=30)
        table.add_column("Source", min_width=8)
        table.add_column("Date", min_width=12)

        for m in memories:
            table.add_row(
                str(m["id"]),
                m["key"],
                m["value"],
                m["source"],
                str(m["created_at"])[:19],
            )

        rprint(table)

    elif intent == "memory_forget":
        parts = user_input.strip().split()
        try:
            memory_id = int(parts[-1])
        except (ValueError, IndexError):
            rprint("[red]Usage: /memory forget <id>[/red]")
            return
        forget_memory(memory_id)
        rprint(f"[green]Memory {memory_id} forgotten.[/green]")

    elif intent == "memory_clear":
        confirmed = confirm_action("Clear all memories? This cannot be undone.")
        if confirmed:
            clear_all_memories()
            rprint("[green]All memories cleared.[/green]")
        else:
            rprint("[yellow]Cancelled.[/yellow]")

    else:
        logger.warning("Unhandled memory intent: %s", intent)
