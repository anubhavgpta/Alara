"""Alara entry point — async startup sequence and REPL."""

import asyncio
import logging

import anyio
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import checkboxlist_dialog
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from alara import db
from alara.core.dispatch import dispatch
from alara.core.errors import AlaraAPIError, AlaraConfigError, AlaraError, AlaraMCPError
from alara.core.gemini import GeminiClient
from alara.core.intent import parse_intent
from alara.core.session import SessionContext, empty_session
from alara.mcp import composio_setup, health
from alara.mcp.client import ComposioMCPClient
from alara.mcp.registry import MCPRegistry
from alara.security import vault
from alara.setup.wizard import (
    is_composio_configured,
    is_setup_complete,
    run_composio_setup,
    run_wizard,
)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "alara.toml"
_HISTORY_PATH = Path.home() / ".alara" / "history"

_console = Console()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # Suppress noisy library loggers — their INFO output interferes with
    # prompt_toolkit's full-screen dialogs (background httpx keepalives write
    # to stderr while the checkboxlist dialog is rendering, corrupting it).
    for _noisy in ("httpx", "httpcore", "mcp", "google_genai", "google.auth"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)


def _load_config() -> dict:
    with _CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def _display_health_table(statuses: list) -> None:
    """Render a rich Table showing per-toolkit Composio health."""
    table = Table(title="Composio Toolkit Status", show_header=True, header_style="bold")
    table.add_column("Toolkit", style="cyan", min_width=14)
    table.add_column("Status", min_width=12)
    table.add_column("Tools", justify="right", min_width=6)
    table.add_column("Auth", min_width=36)

    for s in statuses:
        if s.error:
            status_str = "[red]unavailable[/red]"
            auth_str = f"[red]{s.error[:50]}[/red]"
        elif s.connected:
            status_str = "[green]ready[/green]"
            auth_str = "[green]authed[/green]"
        else:
            status_str = "[yellow]needs auth[/yellow]"
            auth_str = f"[yellow]run: composio add {s.name}[/yellow]"

        table.add_row(s.name, status_str, str(s.tool_count), auth_str)

    _console.print(table)


async def _run_toolkit_selection(statuses: list) -> list[str]:
    """Show a checkboxlist dialog and return the user's selected toolkit names."""
    ready = [s for s in statuses if s.connected and not s.error]
    needs_auth = [s for s in statuses if not s.connected and not s.error]

    values: list[tuple[str, str]] = []
    for s in ready:
        values.append((s.name, f"{s.name}  ({s.tool_count} tools)"))
    for s in needs_auth:
        values.append((s.name, f"{s.name}  — needs auth (composio add {s.name})"))

    if not values:
        return []

    default_values = [s.name for s in ready]

    selected = await checkboxlist_dialog(
        title="Select toolkits for this session",
        text="Use Space to toggle, Enter to confirm. Services marked 'needs auth' will not work until authorised.",
        values=values,
        default_values=default_values,
    ).run_async()

    # dialog returns None on cancel — treat as empty selection
    return selected if selected is not None else []


async def _setup_composio(
    config: dict,
) -> tuple[ComposioMCPClient | None, MCPRegistry, SessionContext]:
    """Create a Composio session, run health checks, and let the user pick toolkits.

    Returns (mcp_client, registry, session_ctx).  On any failure the client is
    None, the registry is empty, and session_ctx has no active toolkits.
    """
    logger = logging.getLogger(__name__)

    toolkits: list[str] = config.get("composio", {}).get("toolkits", [])
    registry = MCPRegistry()

    api_key = vault.get_secret("composio_api_key")
    user_id = vault.get_secret("composio_user_id")

    if not api_key or not user_id:
        _console.print(
            "[yellow]Composio credentials not found in keyring. "
            "Continuing with core capabilities only.[/yellow]"
        )
        return None, registry, empty_session()

    if not toolkits:
        _console.print(
            "[yellow]No Composio toolkits configured. "
            "Continuing with core capabilities only.[/yellow]"
        )
        return None, registry, empty_session()

    # --- Create Composio Tool Router session ---
    try:
        mcp_url = composio_setup.create_session(api_key, user_id, toolkits)
    except (AlaraConfigError, AlaraMCPError) as exc:
        _console.print(
            f"[red]Could not connect to Composio. "
            f"Continuing without external tools.[/red]\n{exc}"
        )
        return None, registry, empty_session()

    # --- Connect MCP client ---
    mcp_client = ComposioMCPClient(mcp_url, api_key, user_id)
    try:
        await mcp_client.connect()
    except AlaraMCPError as exc:
        _console.print(
            f"[red]MCP connection failed. "
            f"Continuing without external tools.[/red]\n{exc}"
        )
        return None, registry, empty_session()

    # --- Health check ---
    statuses = await health.check_all(mcp_client, api_key, user_id, toolkits)
    _console.print()
    _display_health_table(statuses)
    _console.print()

    available_statuses = [s for s in statuses if not s.error]
    if not available_statuses:
        _console.print(
            "[yellow]No toolkits are reachable. "
            "Continuing with core capabilities only.[/yellow]"
        )
        await mcp_client.disconnect()
        return None, registry, empty_session()

    # --- Toolkit selection ---
    selected_toolkits = await _run_toolkit_selection(available_statuses)
    if not selected_toolkits:
        _console.print(
            "[yellow]No toolkits selected. "
            "Continuing with core capabilities only.[/yellow]"
        )
        await mcp_client.disconnect()
        return None, registry, empty_session()

    # --- Build registry from REST API tool metadata ---
    # mcp_client.list_tools() only returns Composio meta-tools (COMPOSIO_*),
    # not the actual toolkit actions.  Fetch real tool schemas per-toolkit
    # via the REST API so the registry contains GMAIL_* etc.
    all_tools: list[dict] = []
    for tk in selected_toolkits:
        all_tools.extend(composio_setup.get_toolkit_tools(api_key, tk))

    registry.load(all_tools)
    active_tools = all_tools  # all fetched tools belong to selected toolkits

    session_ctx = SessionContext(
        composio_mcp_url=mcp_url,
        active_toolkits=selected_toolkits,
        available_tools=all_tools,
        active_tools=active_tools,
        started_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Composio session ready — active toolkits=%s tools=%d",
        selected_toolkits, len(active_tools),
    )
    return mcp_client, registry, session_ctx


async def _main_async() -> None:
    """Full async startup sequence and REPL loop."""
    logger = logging.getLogger(__name__)

    # --- First-run setup ---
    if not is_setup_complete():
        logger.info("No config found — running setup wizard")
        await run_wizard()

    # --- Composio setup (separate from L0 wizard for existing installs) ---
    if not is_composio_configured():
        logger.info("Composio not configured — running Composio setup")
        await run_composio_setup()

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
    except AlaraAPIError as exc:
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

    # --- ASCII banner ---
    from alara.setup.banner import display_banner
    display_banner()

    # --- Composio startup ---
    mcp_client, registry, session_ctx = await _setup_composio(config)

    # --- Inject tool inventory into Gemini system prompt ---
    if session_ctx.active_toolkits:
        fragment = registry.get_system_prompt_fragment(session_ctx.active_toolkits)
        client.append_system_prompt(fragment)

    # --- REPL banner ---
    user_name: str = config.get("user", {}).get("name", "User")
    _console.print(Rule())
    _console.print("[bold cyan]Alara — ready[/bold cyan]", justify="center")
    _console.print("Type your request, or 'exit' to quit.", justify="center")
    _console.print(Rule())
    _console.print()

    # --- REPL ---
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    repl_session: PromptSession = PromptSession(
        history=FileHistory(str(_HISTORY_PATH))
    )
    prompt_str = f"{user_name}> "

    try:
        while True:
            try:
                user_input: str = await repl_session.prompt_async(prompt_str)
                user_input = user_input.strip()
            except (EOFError, KeyboardInterrupt):
                _console.print("\n[cyan]Goodbye.[/cyan]")
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                _console.print("[cyan]Goodbye.[/cyan]")
                break

            try:
                intent = parse_intent(user_input, client)
                response = await dispatch(
                    intent,
                    user_input,
                    client,
                    config,
                    session_ctx=session_ctx,
                    registry=registry,
                    mcp_client=mcp_client,
                )

                _console.print()
                _console.print(response)
                _console.print()

                db.save_message(session_id, "user", user_input)
                db.save_message(session_id, "assistant", response)

            except AlaraError as exc:
                logger.warning("Alara error in REPL loop: %s", exc)
                _console.print(f"[yellow]{exc}[/yellow]")
            except Exception as exc:
                logger.exception("Unhandled error in REPL loop")
                _console.print(
                    f"[bold red]An unexpected error occurred: {exc}[/bold red]"
                )
    finally:
        db.end_session(session_id)
        if mcp_client is not None:
            await mcp_client.disconnect()


def run() -> None:
    """Synchronous CLI entry point — delegates to the async main.

    Uses anyio.run() instead of asyncio.run() so that anyio task groups
    created inside the MCP SDK (streamablehttp_client) are entered and
    exited within the same anyio-managed event loop context.  Using plain
    asyncio.run() causes "Attempted to exit cancel scope in a different task"
    RuntimeErrors when those task groups are cleaned up on shutdown or Ctrl+C.
    """
    _configure_logging()
    anyio.run(_main_async)
