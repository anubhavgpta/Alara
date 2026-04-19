"""Wave-based DAG executor for multi-agent plans."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from rich import print as rprint
from rich.table import Table

from alara.agents.models import Plan, SubTask
from alara.agents.registry import get_registry
from alara.core.errors import AlaraError
from alara.core.session import SessionContext
from alara.security.permissions import confirm_action

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".alara" / "alara.db"


async def execute_plan(plan: Plan, session: SessionContext) -> None:
    """Execute all steps in *plan* using wave-based DAG scheduling."""
    _display_plan_table(plan)

    if not confirm_action(f"Execute plan: {plan.goal}?"):
        rprint("[yellow]Plan cancelled.[/yellow]")
        return

    completed: set[str] = set()
    skipped: set[str] = set()
    statuses: dict[str, str] = {}

    remaining = list(plan.steps)

    while remaining:
        pending_ids = {
            s.id for s in remaining if s.id not in completed and s.id not in skipped
        }

        wave = [
            s for s in remaining
            if s.id in pending_ids
            and all(dep in completed for dep in s.depends_on)
        ]

        if not wave and pending_ids:
            raise AlaraError(
                "DAG scheduling deadlock — possible unresolved dependency"
            )

        if not wave:
            break

        non_destructive = [s for s in wave if not s.is_destructive]
        destructive = [s for s in wave if s.is_destructive]

        # Non-destructive steps run in parallel via ThreadPoolExecutor.
        # _run_step_sync is a plain sync function — safe to submit to a thread.
        if non_destructive:
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures: dict[Future, SubTask] = {
                    pool.submit(_run_step_sync, plan.id, step, session): step
                    for step in non_destructive
                }
                for future, step in futures.items():
                    try:
                        future.result()
                        completed.add(step.id)
                        statuses[step.id] = "success"
                    except Exception as exc:
                        outcome = await _handle_step_failure(
                            plan.id, step, exc, session
                        )
                        statuses[step.id] = outcome
                        if outcome == "aborted":
                            rprint("[red]Plan aborted.[/red]")
                            _print_summary(plan, statuses)
                            return
                        elif outcome == "skipped":
                            skipped.add(step.id)
                        else:
                            completed.add(step.id)

        # Destructive steps run sequentially with individual permission gates.
        # Use asyncio.to_thread so the sync _run_step_sync (which may call
        # asyncio.run() internally for async capability handlers) runs in a
        # thread rather than in the current async context — avoids the
        # "cannot call asyncio.run() from a running loop" error.
        for step in destructive:
            if not confirm_action(
                f"Run destructive step {step.id}: {step.description}?"
            ):
                skipped.add(step.id)
                statuses[step.id] = "skipped"
                _log_step(plan.id, step, "skipped", 0)
                continue
            try:
                await asyncio.to_thread(_run_step_sync, plan.id, step, session)
                completed.add(step.id)
                statuses[step.id] = "success"
            except Exception as exc:
                outcome = await _handle_step_failure(plan.id, step, exc, session)
                statuses[step.id] = outcome
                if outcome == "aborted":
                    rprint("[red]Plan aborted.[/red]")
                    _print_summary(plan, statuses)
                    return
                elif outcome == "skipped":
                    skipped.add(step.id)
                else:
                    completed.add(step.id)

        remaining = [
            s for s in remaining
            if s.id not in completed and s.id not in skipped
        ]

    _print_summary(plan, statuses)


def _run_step_sync(plan_id: str, step: SubTask, session: SessionContext) -> None:
    """Invoke the capability handler for *step* (sync; safe for ThreadPoolExecutor)."""
    t0 = time.monotonic()
    registry = get_registry()
    entry = registry[step.capability]
    entry.handler(
        intent=step.capability,
        user_input=step.description,
        session=session,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    _log_step(plan_id, step, "success", duration_ms)


async def _handle_step_failure(
    plan_id: str,
    step: SubTask,
    exc: Exception,
    session: SessionContext,
) -> str:
    """Prompt retry/skip/abort after a step failure; return the resulting status."""
    rprint(f"[red]Step {step.id} failed: {exc}[/red]")
    try:
        raw = input("Step failed. Choice [retry/skip/abort]: ").strip().lower()
    except EOFError:
        raw = "skip"

    if raw == "retry":
        try:
            await asyncio.to_thread(_run_step_sync, plan_id, step, session)
            return "success"
        except Exception as exc2:
            rprint(f"[red]Step {step.id} failed again: {exc2}[/red]")
            _log_step(plan_id, step, "failed", 0, error=str(exc2))
            return "failed"
    elif raw == "abort":
        _log_step(plan_id, step, "failed", 0, error=str(exc))
        return "aborted"
    else:
        _log_step(plan_id, step, "skipped", 0, error=str(exc))
        return "skipped"


def _display_plan_table(plan: Plan) -> None:
    table = Table(title=f"Plan: {plan.goal}", show_header=True, header_style="bold")
    table.add_column("#", min_width=4)
    table.add_column("Capability", min_width=12)
    table.add_column("Description", min_width=30)
    table.add_column("Depends On", min_width=12)
    table.add_column("Destructive", min_width=10)

    for step in plan.steps:
        depends = ", ".join(step.depends_on) if step.depends_on else "-"
        destructive = "[red]Yes[/red]" if step.is_destructive else "[green]No[/green]"
        table.add_row(step.id, step.capability, step.description, depends, destructive)

    rprint(table)


def _print_summary(plan: Plan, statuses: dict[str, str]) -> None:
    table = Table(title="Plan Execution Summary", show_header=True, header_style="bold")
    table.add_column("Step ID", min_width=8)
    table.add_column("Capability", min_width=12)
    table.add_column("Status", min_width=10)

    for step in plan.steps:
        status = statuses.get(step.id, "unknown")
        if status == "success":
            status_str = "[green]success[/green]"
        elif status == "skipped":
            status_str = "[yellow]skipped[/yellow]"
        else:
            status_str = "[red]failed[/red]"
        table.add_row(step.id, step.capability, status_str)

    rprint(table)


def _log_step(
    plan_id: str,
    step: SubTask,
    status: str,
    duration_ms: int,
    tokens_used: int = 0,
    error: str | None = None,
) -> None:
    try:
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.execute(
            """
            INSERT INTO agent_runs
                (plan_id, step_id, capability, status, tokens_used, duration_ms,
                 error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (plan_id, step.id, step.capability, status, tokens_used, duration_ms, error),
        )
        conn.commit()
        conn.close()
    except Exception as log_exc:
        logger.warning("Failed to log step %s: %s", step.id, log_exc)
