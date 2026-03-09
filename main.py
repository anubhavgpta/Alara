"""Command-line entry point for ALARA v0.2.0 planner preview."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from alara.core.chain import ChainContext, PlanResult
from alara.core.code_context import CodeContextBuilder
from alara.core.goal_understander import GoalUnderstander
from alara.core.orchestrator import Orchestrator
from alara.core.planner import Planner, PlanningError
from alara.memory import MemoryManager
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import StepStatus, TaskGraph
from alara.utils.paths import is_setup_complete, get_log_path


VERSION = "v0.3.0"
console = Console()


def _show_home_screen() -> None:
    """Display the ALARA home screen."""
    try:
        from alara.utils.paths import get_profile_path, get_config_path
        
        # Load profile and config
        profile = {}
        config = {}
        
        try:
            with open(get_profile_path()) as f:
                profile = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
            
        try:
            with open(get_config_path()) as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        # Get memory stats
        memory = MemoryManager.get_instance()
        health = memory.health_check()
        
        session_count = health.get("session_goals", 0)
        preference_count = health.get("total_preferences", 0)
        
        # Build home panel
        home_text = Text()
        home_text.append(f"ALARA", style="bold #9B59FF")
        home_text.append(f"{' ' * 20}v{VERSION}\n", style="dim")
        
        name = profile.get("preferred_name", profile.get("name", "User"))
        home_text.append(f"Hey {name} 👋\n\n", style="bold")
        
        model = config.get("model", "unknown")
        provider = config.get("provider", "unknown")
        home_text.append(f"Model    {model}\n")
        home_text.append(f"Memory   {session_count} sessions · {preference_count} preferences\n")
        home_text.append("Status   Ready", style="green")
        
        console.print(Panel(
            home_text,
            border_style="#9B59FF",
            padding=(1, 2)
        ))
        
        # Show recent goals
        if session_count > 0:
            console.print("\nRecent goals:")
            console.print("─" * 20)
            
            recent_goals = memory.session.get_recent(limit=3)
            for goal in recent_goals:
                console.print(f"• {goal.goal[:60]}{'...' if len(goal.goal) > 60 else ''}")
        
        console.print("\n❯ What would you like to do?")
        
    except Exception as e:
        # Fallback home screen if anything fails
        console.print(Panel(
            Text.from_markup(f"ALARA v{VERSION}\n\nHey User 👋\n\nStatus: Ready", style="bold #9B59FF"),
            border_style="#9B59FF"
        ))
        console.print("\n❯ What would you like to do?")


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
    parser.add_argument(
        "--then",
        action="append",
        dest="then_goals",
        metavar="GOAL",
        help="Chain additional goals after the main goal"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="After each goal, prompt for the next goal"
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune old sessions from memory database"
    )
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
    chain_context: Optional[ChainContext] = None,
) -> PlanResult:
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

    # Build code context before planning
    code_context_builder = CodeContextBuilder()
    code_context = code_context_builder.build(
        goal=goal_context.goal,
        working_dir=str(goal_context.working_directory) if goal_context.working_directory else None,
        goal_scope=goal_context.scope
    )
    if debug and code_context and code_context.strip():
        console.print("[bold bright_magenta]Code Context Summary:[/bold bright_magenta]")
        console.print(code_context[:500] + "..." if len(code_context) > 500 else code_context)

    console.print("[dim]Planning...[/dim]")
    
    # Build chain context block if provided
    chain_context_block = None
    if chain_context and not chain_context.is_empty:
        chain_context_block = chain_context.build_context_block()
        if debug:
            console.print("[bold bright_magenta]Chain Context:[/bold bright_magenta]")
            console.print(chain_context_block)
    
    task_graph = planner.plan(goal_context, memory_context, code_context, chain_context_block)
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
            return PlanResult(
                task_graph=None,
                execution_log=[],
                success=False
            )

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
        
        if planner.last_approach_response:
            rprint("\n[bold]Pass 1 Approach:[/bold]")
            try:
                approach_data = json.loads(planner.last_approach_response)
                console.print_json(json.dumps(approach_data, indent=2))
            except Exception:
                console.print(planner.last_approach_response)
        
        console.print(
            f"[dim]Debug: steps={len(task_graph.steps)} | created_at={task_graph.created_at}[/dim]"
        )
        
        # Print memory health and context summary
        console.print("\n[bold bright_magenta]Memory Health:[/bold bright_magenta]")
        memory_health = memory.health_check()
        console.print(Syntax(json.dumps(memory_health, indent=2), "json", theme="monokai", line_numbers=False))
    
    # Return PlanResult for chaining
    return PlanResult(
        task_graph=task_graph,
        execution_log=orchestrator.last_execution_log,
        success=result.success
    )


def _run_interactive(
    understander: GoalUnderstander,
    planner: Planner,
    orchestrator: Orchestrator,
    debug: bool,
) -> None:
    """Run interactive mode with home screen."""
    while True:
        _show_home_screen()
        
        try:
            raw_input = input("❯ ").strip()
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


def cli_entry() -> int:
    """Entry point for `alara` CLI command."""
    load_dotenv()
    
    # Setup logging to use ~/.alara/alara.log
    logger.remove()
    logger.add(
        str(get_log_path()),
        rotation="10 MB",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )
    
    # Check if setup is complete
    if not is_setup_complete():
        console.print("[yellow]Alara is not set up yet.[/yellow]")
        from alara.setup import run_setup
        run_setup()
        return 0
    
    return main()


def main(argv: Optional[list[str]] = None) -> int:
    # Initialize MemoryManager once
    memory = MemoryManager.get_instance()
    
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.debug:
        os.environ["DEBUG"] = "true"

    # Handle prune command
    if args.prune:
        deleted = memory.db.prune_old_sessions(
            keep_recent=200
        )
        console.print(
            f"[green]Pruned {deleted} old sessions. "
            f"Database compacted.[/green]"
        )
        return 0

    _print_banner()

    understander = GoalUnderstander()
    try:
        planner = Planner()
        orchestrator = Orchestrator()
    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if args.goal:
        # Initialize chain context
        chain = ChainContext()
        
        # Build goal list
        all_goals = [args.goal]
        if args.then_goals:
            all_goals.extend(args.then_goals)
        
        # Execute all goals in the chain
        for i, goal in enumerate(all_goals):
            if len(all_goals) > 1:
                console.print(f"\n[bold]Goal {i+1}/{len(all_goals)}:[/bold] {goal}")
            
            try:
                result = _run_plan(
                    goal, understander, planner,
                    orchestrator, args.debug,
                    auto_confirm=True,
                    chain_context=chain if not chain.is_empty else None
                )
                chain.add(
                    goal=goal,
                    task_graph=result.task_graph,
                    execution_log=result.execution_log,
                    success=result.success
                )
            except PlanningError as exc:
                console.print(f"[red]Planning failed: {exc}[/red]")
                # Continue to next goal even if current one fails
                continue
        
        # Interactive mode after --then goals
        if args.interactive:
            while True:
                try:
                    next_goal = console.input(
                        "\n[dim]Chain another goal? "
                        "(Enter to exit)[/dim] "
                    ).strip()
                except (KeyboardInterrupt, EOFError):
                    break
                if not next_goal:
                    break
                
                try:
                    result = _run_plan(
                        next_goal, understander, planner,
                        orchestrator, args.debug,
                        auto_confirm=True,
                        chain_context=chain
                    )
                    chain.add(
                        goal=next_goal,
                        task_graph=result.task_graph,
                        execution_log=result.execution_log,
                        success=result.success
                    )
                except PlanningError as exc:
                    console.print(f"[red]Planning failed: {exc}[/red]")
                    continue
        
        # Show chain summary if more than one goal
        if len(chain.goals) > 1:
            console.print(f"\n[bold]Chain complete:[/bold] {chain.summary()}")
        
        return 0

    # No goal provided, run interactive mode
    _run_interactive(understander, planner, orchestrator, args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


    print('hello world')
