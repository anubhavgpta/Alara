"""Command-line entry point for ALARA v0.2.0 planner preview."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Optional

from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from alara.core.goal_understander import GoalUnderstander
from alara.core.orchestrator import Orchestrator
from alara.core.planner import Planner, PlanningError
from alara.memory import MemoryManager
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import StepStatus, TaskGraph


VERSION = "v0.2.0"
console = Console()


def _print_banner() -> None:
    banner = Text()
    banner.append("ALARA\n", style="bold bright_magenta")
    banner.append("Ambient Language & Reasoning Assistant\n", style="magenta")
    banner.append(VERSION, style="dim")
    console.print(Panel(banner, border_style="bright_magenta", padding=(1, 3)))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ALARA - Agentic Desktop AI")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--goal", type=str, default=None, help="Run a single goal and exit")
    return parser


def _render_goal_context(goal_context: GoalContext) -> None:
    context_json = goal_context.model_dump_json(indent=2)
    console.print(Syntax(context_json, "json", theme="monokai", line_numbers=False))


def _render_task_graph(task_graph: TaskGraph) -> None:
    type_styles = {
        "filesystem": "green",
        "cli": "yellow",
        "app_adapter": "blue",
        "system": "cyan",
        "ui_automation": "red",
        "vision": "magenta",
    }

    table = Table(show_lines=False, header_style="bold bright_magenta")
    table.add_column("ID", width=4)
    table.add_column("Type", width=12)
    table.add_column("Operation", width=20)
    table.add_column("Description", width=40)
    table.add_column("Verification", width=22)
    table.add_column("Deps", width=8)

    for step in task_graph.steps:
        deps = ",".join(str(dep) for dep in step.depends_on) if step.depends_on else "-"
        step_type = step.step_type.value
        table.add_row(
            str(step.id),
            f"[{type_styles.get(step_type, 'white')}]{step_type}[/{type_styles.get(step_type, 'white')}]",
            step.operation,
            step.description,
            step.verification_method,
            deps,
        )
    console.print(table)


def _print_progress(step, step_result) -> None:
    """Print progress for each completed step."""
    if step_result.success:
        console.print(
            f"[PASS] Step {step.id} [{step.step_type.value}] {step.operation} — {step.description[:50]}",
            style="green"
        )
    elif step.status == StepStatus.SKIPPED:
        console.print(
            f"[SKIP] Step {step.id} [{step.step_type.value}] {step.operation} — {step.description[:50]} (skipped)",
            style="yellow"
        )
    else:
        console.print(
            f"[FAIL] Step {step.id} [{step.step_type.value}] {step.operation} — {step.description[:50]}",
            style="red"
        )


def _run_plan(
    raw_input: str,
    understander: GoalUnderstander,
    planner: Planner,
    orchestrator: Orchestrator,
    debug: bool,
    auto_confirm: bool = False,
) -> None:
    # Get memory manager instance
    memory = MemoryManager.get_instance()
    
    goal_context = understander.understand(raw_input)
    if debug:
        _render_goal_context(goal_context)

    # Build memory context before planning
    memory_context = memory.build_context(raw_input, goal_context)
    if debug:
        console.print("[bold bright_magenta]Memory Context Summary:[/bold bright_magenta]")
        console.print(memory_context.summary[:500] + "..." if len(memory_context.summary) > 500 else memory_context.summary)

    console.print("[dim]Planning...[/dim]")
    task_graph = planner.plan(goal_context, memory_context)
    _render_task_graph(task_graph)

    console.print(f"Goal: {task_graph.goal}")
    console.print(
        "Scope: {}  |  Complexity: {}  |  Steps: {}".format(
            goal_context.scope,
            goal_context.estimated_complexity,
            len(task_graph.steps),
        )
    )
    
    console.print("─" * 80)
    
    # Ask for confirmation unless auto-confirm is enabled
    if not auto_confirm:
        console.print("Execute this plan? [y/n]: ", end="")
        confirm = input().strip().lower()
        if confirm != "y":
            console.print("Plan cancelled.", style="dim")
            return

    console.print("[dim]Executing...[/dim]")
    
    # Start session tracking before execution
    entry_id = memory.session.start_goal(raw_input, goal_context)
    
    # Track execution time
    start_time = time.monotonic()
    
    # Run the orchestrator
    result = orchestrator.run(task_graph, progress_callback=_print_progress)
    
    # Calculate execution duration
    duration_ms = (time.monotonic() - start_time) * 1000
    
    # Update memory after execution
    memory.after_execution(
        raw_input, goal_context, task_graph,
        result, entry_id, duration_ms
    )
    
    # Print final result
    if result.success:
        console.print(
            f"[PASS] Task complete — {result.steps_completed}/{result.total_steps} steps",
            style="green"
        )
    else:
        console.print(
            f"[FAIL] Task failed — {result.steps_completed}/{result.total_steps} steps completed",
            style="red"
        )
        console.print(result.message, style="red")
    
    # Print debug info if requested
    if debug and result.execution_log:
        console.print("\n[bold bright_magenta]Execution Log:[/bold bright_magenta]")
        console.print(Syntax(json.dumps(result.execution_log, indent=2), "json", theme="monokai", line_numbers=False))

    if debug:
        if planner.last_raw_response:
            rprint("[bold bright_magenta]Raw Gemini response:[/bold bright_magenta]")
            console.print(Syntax(planner.last_raw_response, "json", theme="monokai", line_numbers=False))
        console.print(
            f"[dim]Debug: steps={len(task_graph.steps)} | created_at={task_graph.created_at}[/dim]"
        )
        
        # Print memory health and context summary
        console.print("\n[bold bright_magenta]Memory Health:[/bold bright_magenta]")
        memory_health = memory.health_check()
        console.print(Syntax(json.dumps(memory_health, indent=2), "json", theme="monokai", line_numbers=False))


def _run_interactive(
    understander: GoalUnderstander,
    planner: Planner,
    orchestrator: Orchestrator,
    debug: bool,
) -> None:
    console.print("Alara is ready. Describe what you want to accomplish.")
    console.print("Type 'exit' or press Ctrl+C to quit.")
    while True:
        try:
            raw_input = input("> ").strip()
        except KeyboardInterrupt:
            console.print("\nShutting down.")
            break

        if not raw_input:
            continue
        if raw_input.lower() in {"exit", "quit"}:
            console.print("Shutting down.")
            break

        try:
            _run_plan(raw_input, understander, planner, orchestrator, debug)
        except PlanningError as exc:
            console.print(f"[red]Planning failed: {exc}[/red]")


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv()
    
    # Initialize MemoryManager once, after load_dotenv
    memory = MemoryManager.get_instance()
    
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.debug:
        os.environ["DEBUG"] = "true"

    _print_banner()

    understander = GoalUnderstander()
    try:
        planner = Planner()
        orchestrator = Orchestrator()
    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if args.goal:
        try:
            _run_plan(args.goal, understander, planner, orchestrator, args.debug, auto_confirm=True)
            return 0
        except PlanningError as exc:
            console.print(f"[red]Planning failed: {exc}[/red]")
            return 1

    _run_interactive(understander, planner, orchestrator, args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
