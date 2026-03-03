"""Command-line entry point for ALARA v0.2.0."""

from __future__ import annotations

import argparse
import os
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from alara.core.orchestrator import AlaraOrchestrator


VERSION = "v0.2.0"
console = Console()


def _print_banner() -> None:
    """Render the startup banner for ALARA."""
    banner = Text()
    banner.append("ALARA — Agentic Desktop AI\n", style="bold bright_cyan")
    banner.append(f"{VERSION}", style="dim")
    console.print(Panel(banner, border_style="bright_cyan", padding=(1, 4)))


def _build_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for interactive and one-shot modes."""
    parser = argparse.ArgumentParser(description="ALARA - Agentic Desktop AI")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--goal", type=str, default=None, help="Run a single goal and exit")
    return parser


def _run_single_goal(orchestrator: AlaraOrchestrator, goal: str) -> None:
    """Execute one goal in non-interactive mode."""
    orchestrator.run(goal)


def _run_interactive(orchestrator: AlaraOrchestrator) -> None:
    """Start the continuous goal prompt loop."""
    console.print("Alara is ready. Describe what you want to accomplish.")
    while True:
        goal = input("> ").strip()
        if not goal:
            continue
        if goal.lower() in {"exit", "quit"}:
            console.print("Shutting down Alara.")
            return
        orchestrator.run(goal)


def main(argv: Optional[list[str]] = None) -> int:
    """Application entrypoint for ALARA CLI."""
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.debug:
        os.environ["DEBUG"] = "true"

    _print_banner()
    orchestrator = AlaraOrchestrator()

    try:
        if args.goal:
            _run_single_goal(orchestrator, args.goal)
            return 0
        _run_interactive(orchestrator)
        return 0
    except KeyboardInterrupt:
        console.print("\nInterrupted. Shutting down Alara.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
