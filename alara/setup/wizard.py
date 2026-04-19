"""First-run setup wizard for Alara — L0 + L1 Composio setup."""

import logging
import re
import tomllib
from pathlib import Path

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from alara.security import vault

logger = logging.getLogger(__name__)
_console = Console()

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "alara.toml"
_VERSION = "0.1.0"

_GEMINI_DEFAULTS: dict = {
    "primary_model": "gemini-2.5-flash",
    "fallback_model": "gemini-2.5-flash-lite",
    "request_timeout_seconds": 30,
    "max_retries": 4,
}

_KNOWN_TOOLKITS: list[tuple[str, str]] = [
    ("gmail",          "Gmail — read, search, and send email"),
    ("slack",          "Slack — messages and channels"),
    ("github",         "GitHub — repositories, issues, PRs"),
    ("notion",         "Notion — pages and databases"),
    ("googlecalendar", "Google Calendar — events and scheduling"),
    ("linear",         "Linear — issues and projects"),
]

# One shared PromptSession for the entire wizard lifecycle.
# prompt_async() is safe to call inside a running event loop.
_session: PromptSession = PromptSession()


async def _ask(message: str, *, is_password: bool = False) -> str:
    """Thin wrapper around PromptSession.prompt_async() for wizard prompts."""
    return await _session.prompt_async(message, is_password=is_password)


# ---------------------------------------------------------------------------
# L0 field collectors
# ---------------------------------------------------------------------------

async def _collect_name() -> str:
    while True:
        value = (await _ask("Your name: ")).strip()
        if value:
            return value
        _console.print("[yellow]Name cannot be empty. Please try again.[/yellow]")


async def _collect_api_key() -> str:
    while True:
        value = (await _ask("Gemini API key: ", is_password=True)).strip()
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


async def _collect_workspace() -> str:
    default = Path.home() / "alara-workspace"
    while True:
        raw = (await _ask(f"Workspace directory [{default}]: ")).strip()
        chosen = Path(raw).expanduser() if raw else default
        resolved = chosen.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        logger.debug("Workspace directory: %s", resolved)
        return str(resolved)


async def _collect_response_style() -> str:
    while True:
        value = (
            await _ask("Response style — enter 1 for concise, 2 for detailed [1]: ")
        ).strip()
        if value in ("", "1"):
            return "concise"
        if value == "2":
            return "detailed"
        _console.print("[yellow]Please enter 1 or 2.[/yellow]")


async def _collect_timezone() -> str:
    while True:
        value = (
            await _ask(
                "Your timezone (e.g. Asia/Kolkata, Europe/London, America/New_York): "
            )
        ).strip()
        if not value:
            _console.print("[yellow]Timezone cannot be empty. Please try again.[/yellow]")
            continue
        if "/" not in value:
            _console.print(
                "[yellow]Timezone must contain '/' (e.g. Europe/London). "
                "Please try again.[/yellow]"
            )
            continue
        return value


# ---------------------------------------------------------------------------
# L1 Composio field collectors
# ---------------------------------------------------------------------------

async def _collect_composio_api_key() -> str:
    """Prompt for and store the Composio API key (keyring only)."""
    _console.print(
        "Get your API key from [cyan]dashboard.composio.dev[/cyan] "
        "under Settings -> API Keys."
    )
    while True:
        value = (await _ask("Composio API key: ", is_password=True)).strip()
        if not value:
            _console.print("[yellow]API key cannot be empty. Please try again.[/yellow]")
            continue
        vault.store_secret("composio_api_key", value)
        logger.debug("Composio API key stored in vault")
        return value


async def _collect_composio_user_id() -> str:
    """Prompt for and store the Composio user ID (keyring only)."""
    _console.print(
        "The user ID scopes your Composio session. "
        "Your email address is a good choice."
    )
    while True:
        value = (
            await _ask(
                "User identifier for this Composio session (e.g. your email): "
            )
        ).strip()
        if not value:
            _console.print("[yellow]User ID cannot be empty. Please try again.[/yellow]")
            continue
        vault.store_secret("composio_user_id", value)
        logger.debug("Composio user ID stored in vault")
        return value


async def _collect_toolkits() -> list[str]:
    """Display a numbered list of toolkits and return the user's selection."""
    _console.print()
    _console.print("[cyan]Which toolkits do you want Alara to have access to?[/cyan]")
    _console.print(
        "After setup, connect each service by running "
        "[bold]composio add <toolkit>[/bold] in your terminal."
    )
    _console.print()

    for idx, (name, description) in enumerate(_KNOWN_TOOLKITS, start=1):
        _console.print(f"  {idx}. [bold]{name}[/bold] — {description}")

    _console.print()

    while True:
        raw = (
            await _ask('Enter numbers separated by commas, or "all" [all]: ')
        ).strip()

        if not raw or raw.lower() == "all":
            return [name for name, _ in _KNOWN_TOOLKITS]

        selected: list[str] = []
        valid = True
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                _console.print(
                    f"[yellow]'{part}' is not a number. "
                    f"Please enter comma-separated numbers or 'all'.[/yellow]"
                )
                valid = False
                break
            idx_val = int(part)
            if idx_val < 1 or idx_val > len(_KNOWN_TOOLKITS):
                _console.print(
                    f"[yellow]Number {idx_val} is out of range "
                    f"(1-{len(_KNOWN_TOOLKITS)}).[/yellow]"
                )
                valid = False
                break
            selected.append(_KNOWN_TOOLKITS[idx_val - 1][0])

        if valid and selected:
            return selected
        if valid and not selected:
            _console.print("[yellow]Please select at least one toolkit.[/yellow]")


# ---------------------------------------------------------------------------
# Config writers
# ---------------------------------------------------------------------------

def _write_config(
    name: str,
    timezone: str,
    response_style: str,
    workspace: str,
) -> None:
    """Write a complete alara.toml (no secrets).

    Connected app toolkits are discovered dynamically from Composio at
    startup — no static list is written here.
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_workspace = Path(workspace).as_posix()
    gd = _GEMINI_DEFAULTS

    content = f"""[user]
name = "{name}"
timezone = "{timezone}"
response_style = "{response_style}"

[workspace]
path = "{safe_workspace}"

[alara]
version = "{_VERSION}"
first_run_complete = true

[gemini]
primary_model = "{gd['primary_model']}"
fallback_model = "{gd['fallback_model']}"
request_timeout_seconds = {gd['request_timeout_seconds']}
max_retries = {gd['max_retries']}

[composio]
"""
    _CONFIG_PATH.write_text(content, encoding="utf-8")
    logger.debug("Config written to %s", _CONFIG_PATH)


def _patch_composio_to_config() -> None:
    """Add or replace the [composio] section in an existing alara.toml.

    The section is a marker only — connected apps are discovered dynamically
    from Composio at startup, not listed here.
    """
    content = _CONFIG_PATH.read_text(encoding="utf-8")
    content = re.sub(r"\[composio\].*?(?=\n\[|\Z)", "", content, flags=re.DOTALL).rstrip()
    content = content + "\n\n[composio]\n"
    _CONFIG_PATH.write_text(content, encoding="utf-8")
    logger.debug("Patched [composio] section in %s", _CONFIG_PATH)


# ---------------------------------------------------------------------------
# Public entry points (all async — called from within a running event loop)
# ---------------------------------------------------------------------------

async def run_wizard() -> dict:
    """Run the full first-run setup wizard (L0 + L1 Composio steps)."""
    from alara.setup.banner import display_banner

    display_banner()
    _console.print(Rule())
    _console.print(
        Text("Welcome to Alara", style="bold cyan", justify="center"),
        justify="center",
    )
    _console.print(
        Text("Ambient Language and Reasoning Assistant", style="cyan", justify="center"),
        justify="center",
    )
    _console.print(Rule())
    _console.print()

    name = await _collect_name()
    await _collect_api_key()
    workspace = await _collect_workspace()
    response_style = await _collect_response_style()
    timezone = await _collect_timezone()

    _console.print()
    _console.print(Rule())
    _console.print("[bold cyan]Composio setup[/bold cyan]", justify="center")
    _console.print(
        "Alara uses Composio to connect to Gmail, Slack, GitHub, and more.",
        justify="center",
    )
    _console.print(Rule())
    _console.print()

    await _collect_composio_api_key()
    await _collect_composio_user_id()

    _write_config(name, timezone, response_style, workspace)

    _console.print()
    _console.print(f"[bold green]Setup complete. Starting Alara, {name}.[/bold green]")
    _console.print(
        "Connect apps with [bold]composio add <app>[/bold] — "
        "Alara discovers them automatically on startup."
    )
    _console.print()

    return {
        "user": {"name": name, "timezone": timezone, "response_style": response_style},
        "workspace": {"path": workspace},
        "alara": {"version": _VERSION, "first_run_complete": True},
        "gemini": dict(_GEMINI_DEFAULTS),
        "composio": {},
    }


async def run_composio_setup() -> None:
    """Run only the Composio setup steps for an existing L0 installation."""
    _console.print()
    _console.print(Rule())
    _console.print("[bold cyan]Composio setup[/bold cyan]", justify="center")
    _console.print(Rule())
    _console.print()
    _console.print(
        "Alara uses Composio to connect to external services like Gmail, "
        "Slack, and GitHub."
    )
    _console.print("Get your API key at [cyan]dashboard.composio.dev[/cyan].")
    _console.print()

    await _collect_composio_api_key()
    await _collect_composio_user_id()

    _patch_composio_to_config()

    _console.print()
    _console.print("[bold green]Composio setup complete.[/bold green]")
    _console.print(
        "Connect apps with [bold]composio add <app>[/bold] — "
        "Alara discovers them automatically on startup."
    )
    _console.print()


def is_setup_complete() -> bool:
    """Return True if alara.toml exists and first_run_complete is true."""
    if not _CONFIG_PATH.exists():
        return False
    try:
        with _CONFIG_PATH.open("rb") as fh:
            config = tomllib.load(fh)
        return bool(config.get("alara", {}).get("first_run_complete", False))
    except Exception as exc:
        logger.warning("Could not read config: %s", exc)
        return False


def is_composio_configured() -> bool:
    """Return True if Composio credentials are stored in the vault.

    Connected apps are discovered dynamically at startup — no toolkit list
    in alara.toml is required.
    """
    return bool(
        vault.get_secret("composio_api_key")
        and vault.get_secret("composio_user_id")
    )
