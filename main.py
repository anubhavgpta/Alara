"""Command-line entry point for ALARA v0.3.0 master orchestrator."""

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
from alara.core.master_orchestrator import MasterOrchestrator
from alara.core.orchestrator import Orchestrator
from alara.core.planner import Planner, PlanningError
from alara.agents.registry import AgentRegistry
from alara.memory import MemoryManager
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import StepStatus, TaskGraph
from alara.utils.paths import is_setup_complete, get_log_path, get_config_path, get_profile_path


VERSION = "v0.4.1"
console = Console()


def _show_home_screen() -> None:
    """Display the ALARA home screen."""
    try:
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
        
        # Initialize agent registry to get active agents
        registry = AgentRegistry(config, profile)
        active = registry.get_registered_names()
        warm = registry.get_warm_names()
        
        # Discover connected Composio services
        connected_services = []
        if "comms" in active:
            try:
                from alara.capabilities.composio_capability import ComposioCapability
                cap = ComposioCapability(config)
                connected_services = cap.discover_and_cache()
            except Exception:
                pass
        
        # Get memory stats
        memory = MemoryManager.get_instance()
        health = memory.health_check()
        
        # Use database session count instead of current session entries
        session_count = health.get("database", {}).get("table_counts", {}).get("sessions", 0)
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
        home_text.append(f"Agents   {', '.join(active)} ({len(warm)} warm)\n")
        
        # Show connected Composio services if any
        if connected_services:
            services_str = ", ".join(connected_services)
            home_text.append(f"Comms    {services_str} (via Composio)\n")
        
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


def _load_config() -> dict:
    """Load configuration from file or environment variables."""
    path = get_config_path()
    if path.exists():
        import json
        return json.loads(path.read_text())
    # Fallback to env vars
    return {
        "provider": "gemini",
        "model": os.getenv(
            "GEMINI_MODEL", "gemini-2.5-flash"
        ),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
    }


def _load_profile() -> dict:
    """Load user profile from file."""
    path = get_profile_path()
    if path.exists():
        import json
        return json.loads(path.read_text())
    return {}


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


def _run_goal(
    goal: str,
    master: MasterOrchestrator,
    console: Console,
    debug: bool = False,
    chain_context: ChainContext = None
) -> list:
    """Run a goal using the master orchestrator."""
    from alara.memory import MemoryManager
    from alara.core.goal_understander import GoalUnderstander
    from datetime import datetime
    import time
    
    memory = MemoryManager.get_instance()
    
    # Start goal session
    goal_understander = GoalUnderstander(
        model=master.config.get("model", "gemini-2.5-flash"),
        api_key=master.config.get("api_key", ""),
        provider=master.config.get("provider", "gemini")
    )
    goal_context = goal_understander.understand(goal)
    entry_id = memory.session.start_goal(goal, goal_context)
    
    start_time = time.time()
    results = master.run(goal, console=console)
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Collect all key_outputs from results
    all_key_outputs = []
    for result in results:
        all_key_outputs.extend(result.key_outputs)
    
    # Create OrchestratorResult for memory logging
    from alara.core.orchestrator import OrchestratorResult
    total_steps = sum(r.steps_total for r in results)
    completed_steps = sum(r.steps_completed for r in results)
    failed_steps = sum(r.steps_failed for r in results)
    overall_success = all(r.success for r in results)
    
    orchestrator_result = OrchestratorResult(
        success=overall_success,
        steps_completed=completed_steps,
        steps_failed=failed_steps,
        steps_skipped=0,  # Not tracked at this level
        total_steps=total_steps,
        message="",
        execution_log=[]
    )
    
    # Log to memory with key_outputs
    memory.after_execution(
        goal=goal,
        goal_context=goal_context,
        task_graph=None,  # Not available at this level
        result=orchestrator_result,
        entry_id=entry_id,
        duration_ms=duration_ms,
        key_outputs=all_key_outputs
    )

    for result in results:
        if result.success:
            console.print(
                f"[green][PASS][/green] "
                f"{result.agent_name} agent — "
                f"{result.steps_completed}/"
                f"{result.steps_total} steps"
            )
        else:
            console.print(
                f"[red][FAIL][/red] "
                f"{result.agent_name} agent — "
                f"{result.error or 'unknown error'}"
            )

    # Print debug info if requested
    if debug:
        for result in results:
            if result.execution_log:
                console.print(f"\n[bold bright_magenta]{result.agent_name} Agent Execution Log:[/bold bright_magenta]")
                console.print(Syntax(json.dumps(result.execution_log, indent=2), "json", theme="monokai", line_numbers=False))

    return results


def _run_interactive(
    master: MasterOrchestrator,
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
            _run_goal(raw_input, master, console, debug)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")


def cli_entry() -> int:
    """Entry point for `alara` CLI command."""
    load_dotenv()
    
    # Setup logging to use ~/.alara/alara.log
    logger.remove()
    log_level = "DEBUG" if os.getenv("DEBUG") == "true" else "INFO"
    logger.add(
        str(get_log_path()),
        rotation="10 MB",
        level=log_level,
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

    # Load config and profile
    config = _load_config()
    profile = _load_profile()
    
    # Initialize master orchestrator
    try:
        registry = AgentRegistry(config, profile)
        master = MasterOrchestrator(registry, config, profile)
    except Exception as exc:
        console.print(f"[red]Failed to initialize master orchestrator: {exc}[/red]")
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
                results = _run_goal(
                    goal, master, console, args.debug,
                    chain_context=chain if not chain.is_empty else None
                )
                
                # Add to chain context for next goal
                if results:
                    success = all(r.success for r in results)
                    execution_log = []
                    for result in results:
                        execution_log.extend(result.execution_log)
                    
                    chain.add(
                        goal=goal,
                        task_graph=None,  # Master orchestrator doesn't expose task graph
                        execution_log=execution_log,
                        success=success
                    )
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
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
                    results = _run_goal(
                        next_goal, master, console, args.debug,
                        chain_context=chain
                    )
                    
                    # Add to chain context
                    if results:
                        success = all(r.success for r in results)
                        execution_log = []
                        for result in results:
                            execution_log.extend(result.execution_log)
                        
                        chain.add(
                            goal=next_goal,
                            task_graph=None,
                            execution_log=execution_log,
                            success=success
                        )
                except Exception as exc:
                    console.print(f"[red]Error: {exc}[/red]")
                    continue
        
        # Show chain summary if more than one goal
        if len(chain.goals) > 1:
            console.print(f"\n[bold]Chain complete:[/bold] {chain.summary()}")
        
        return 0

    # No goal provided, run interactive mode
    _run_interactive(master, args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


    print('hello world')
