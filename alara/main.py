"""Alara entry point — REPL and startup sequence."""

import logging
import sys
import tomllib
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.rule import Rule

from alara import db
from alara.core.dispatch import dispatch
from alara.core.gemini import GeminiClient
from alara.core.intent import parse_intent
from alara.setup.wizard import is_setup_complete, run_wizard

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "alara.toml"
_HISTORY_PATH = Path.home() / ".alara" / "history"

_console = Console()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _load_config() -> dict:
    with _CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def run() -> None:
    """Entry point for the `alara` CLI command."""
    _configure_logging()
    logger = logging.getLogger(__name__)

    # --- First-run setup ---
    if not is_setup_complete():
        logger.info("No config found — running setup wizard")
        run_wizard()

    # --- Load config ---
    try:
        config = _load_config()
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        _console.print(f"[bold red]Could not load configuration: {exc}[/bold red]")
        return

    # --- Initialise Gemini ---
    try:
        client = GeminiClient()
    except RuntimeError as exc:
        logger.error("Gemini init failed: %s", exc)
        _console.print(f"[bold red]{exc}[/bold red]")
        return

    # --- Initialise database ---
    try:
        session_id = db.create_session()
        logger.info("Session started: %d", session_id)
    except Exception as exc:
        logger.error("Database init failed: %s", exc)
        _console.print(f"[bold red]Database error: {exc}[/bold red]")
        return

    # --- ASCII banner + REPL banner ---
    from alara.setup.banner import display_banner
    display_banner()
    user_name: str = config.get("user", {}).get("name", "User")
    _console.print(Rule())
    _console.print("[bold cyan]Alara — ready[/bold cyan]", justify="center")
    _console.print(
        "Type your request, or 'exit' to quit.", justify="center"
    )
    _console.print(Rule())
    _console.print()

    # --- REPL ---
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(
        history=FileHistory(str(_HISTORY_PATH))
    )
    prompt_str = f"{user_name}> "

    while True:
        try:
            user_input: str = session.prompt(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            _console.print("\n[cyan]Goodbye.[/cyan]")
            db.end_session(session_id)
            return

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            _console.print("[cyan]Goodbye.[/cyan]")
            db.end_session(session_id)
            return

        try:
            intent = parse_intent(user_input, client)
            response = dispatch(intent, user_input, client, config)

            _console.print()
            _console.print(response)
            _console.print()

            db.save_message(session_id, "user", user_input)
            db.save_message(session_id, "assistant", response)

        except Exception as exc:
            logger.exception("Unhandled error in REPL loop")
            _console.print(
                f"[bold red]An unexpected error occurred: {exc}[/bold red]"
            )
