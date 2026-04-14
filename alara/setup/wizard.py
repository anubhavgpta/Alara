"""First-run setup wizard for Alara."""

import logging
import tomllib
from pathlib import Path

from prompt_toolkit import prompt
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from alara.security import vault

logger = logging.getLogger(__name__)
_console = Console()

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "alara.toml"
_VERSION = "0.1.0"


def _collect_name() -> str:
    """Prompt for and validate the user's name."""
    while True:
        value = prompt("Your name: ").strip()
        if value:
            return value
        _console.print("[yellow]Name cannot be empty. Please try again.[/yellow]")


def _collect_api_key() -> str:
    """Prompt for the Gemini API key, mask input, validate format, then store it."""
    while True:
        value = prompt("Gemini API key: ", is_password=True).strip()
        if not value:
            _console.print("[yellow]API key cannot be empty. Please try again.[/yellow]")
            continue
        if not value.startswith("AI"):
            _console.print(
                "[yellow]API key should start with 'AI'. Please check and try again.[/yellow]"
            )
            continue
        vault.set_secret("gemini_api_key", value)
        logger.debug("Gemini API key stored in vault")
        return value


def _collect_workspace() -> str:
    """Prompt for workspace directory, apply default, create if needed."""
    default = Path.home() / "alara-workspace"
    while True:
        raw = prompt(f"Workspace directory [{default}]: ").strip()
        if not raw:
            chosen = default
        else:
            chosen = Path(raw).expanduser()

        resolved = chosen.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        logger.debug("Workspace directory: %s", resolved)
        return str(resolved)


def _collect_response_style() -> str:
    """Prompt for response style preference."""
    while True:
        value = prompt("Response style — enter 1 for concise, 2 for detailed [1]: ").strip()
        if value in ("", "1"):
            return "concise"
        if value == "2":
            return "detailed"
        _console.print("[yellow]Please enter 1 or 2.[/yellow]")


def _collect_timezone() -> str:
    """Prompt for timezone with basic format validation."""
    while True:
        value = prompt("Your timezone (e.g. Asia/Kolkata, Europe/London, America/New_York): ").strip()
        if not value:
            _console.print("[yellow]Timezone cannot be empty. Please try again.[/yellow]")
            continue
        if "/" not in value:
            _console.print(
                "[yellow]Timezone must contain a '/' (e.g. Europe/London). Please try again.[/yellow]"
            )
            continue
        return value


def _write_config(name: str, timezone: str, response_style: str, workspace: str) -> None:
    """Write alara.toml (no secrets)."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # TOML string values interpret backslashes as escapes, so normalise Windows
    # paths to forward slashes (valid on all platforms including Windows).
    safe_workspace = Path(workspace).as_posix()
    content = f"""[user]
name = "{name}"
timezone = "{timezone}"
response_style = "{response_style}"

[workspace]
path = "{safe_workspace}"

[alara]
version = "{_VERSION}"
first_run_complete = true
"""
    _CONFIG_PATH.write_text(content, encoding="utf-8")
    logger.debug("Config written to %s", _CONFIG_PATH)


def run_wizard() -> dict:
    """Run the interactive first-run setup wizard.

    Returns a dict with the collected configuration (excluding the API key).
    """
    from alara.setup.banner import display_banner
    display_banner()
    _console.print(Rule())
    banner = Text("Welcome to Alara", style="bold cyan", justify="center")
    _console.print(banner, justify="center")
    sub = Text("Ambient Language and Reasoning Assistant", style="cyan", justify="center")
    _console.print(sub, justify="center")
    _console.print(Rule())
    _console.print()

    name = _collect_name()
    _collect_api_key()
    workspace = _collect_workspace()
    response_style = _collect_response_style()
    timezone = _collect_timezone()

    _write_config(name, timezone, response_style, workspace)

    _console.print()
    _console.print(f"[bold green]Setup complete. Starting Alara, {name}.[/bold green]")
    _console.print()

    return {
        "user": {
            "name": name,
            "timezone": timezone,
            "response_style": response_style,
        },
        "workspace": {"path": workspace},
        "alara": {"version": _VERSION, "first_run_complete": True},
    }


def is_setup_complete() -> bool:
    """Return True if the config file exists and first_run_complete is true."""
    if not _CONFIG_PATH.exists():
        return False
    try:
        with _CONFIG_PATH.open("rb") as fh:
            config = tomllib.load(fh)
        return bool(config.get("alara", {}).get("first_run_complete", False))
    except Exception as exc:
        logger.warning("Could not read config: %s", exc)
        return False
