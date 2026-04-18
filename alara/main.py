"""Alara entry point — async startup sequence and REPL."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alara.tasks.queue import TaskQueue

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

from alara import db
from alara.coding.aider_backend import AiderBackend
from alara.coding.base import CodingBackend
from alara.coding.openhands_backend import OpenHandsBackend
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
    from rich.logging import RichHandler
    # RichHandler prevents background thread log output from interleaving with
    # the prompt_toolkit input line. Full thread-safe console lock deferred to L4.
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # Suppress noisy library loggers — their INFO output interferes with
    # prompt_toolkit's full-screen dialogs (background httpx keepalives write
    # to stderr while the checkboxlist dialog is rendering, corrupting it).
    for _noisy in ("httpx", "httpcore", "mcp", "google_genai", "google.auth"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)


def _load_config() -> dict:
    with _CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)



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
    coding_backend: CodingBackend | None = None,
    task_queue: TaskQueue | None = None,
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
    statuses = await health.check_all(
        mcp_client, api_key, user_id, toolkits,
        coding_backend=coding_backend,
        task_queue=task_queue,
    )
    _console.print()
    health.render_health_table(statuses)
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
        health_statuses=list(statuses),
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

    # --- Load memory context into Gemini system prompt ---
    try:
        from alara.memory.context import build_memory_context
        client.set_memory_context(build_memory_context())
        logger.info("Memory context loaded")
    except Exception as _mem_ctx_exc:
        logger.warning("Failed to load memory context: %s", _mem_ctx_exc)

    # --- ASCII banner ---
    from alara.setup.banner import display_banner
    display_banner()

    if len(sys.argv) > 1:
        logging.warning(
            "CLI arguments are not supported. Use the REPL prompt or /code inside Alara."
        )

    # --- Initialise task queue (before Composio so health check can report it) ---
    from alara.tasks.queue import TaskQueue, _console_lock
    db_path = Path.home() / ".alara" / "alara.db"
    task_queue = TaskQueue(db_path=db_path)

    # --- Instantiate coding backend ---
    coding_cfg: dict = config.get("coding", {})
    coding_backend_name: str = coding_cfg.get("backend", "aider")
    coding_backend: CodingBackend
    if coding_backend_name == "openhands":
        coding_backend = OpenHandsBackend(
            base_url=coding_cfg.get("openhands_base_url", "http://localhost:3000"),
            timeout_seconds=int(coding_cfg.get("openhands_timeout_seconds", 120)),
        )
    else:
        coding_backend = AiderBackend(
            aider_model=coding_cfg.get("aider_model", "gemini/gemini-2.5-flash"),
            encoding=coding_cfg.get("aider_encoding", "utf-8"),
        )

    # --- Composio startup ---
    mcp_client, registry, session_ctx = await _setup_composio(
        config, coding_backend=coding_backend, task_queue=task_queue
    )
    session_ctx.coding_backend = coding_backend_name
    session_ctx.session_id = session_id
    session_ctx.task_queue = task_queue
    session_ctx.mcp_client = mcp_client
    session_ctx.gemini_client = client

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

    # Note: /code and other slash commands are REPL-only. CLI argument execution
    # is deferred to a future `alara run "<task>"` interface (planned for L4+).

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

                if response is not None:
                    with _console_lock:
                        _console.print()
                        _console.print(response)
                        _console.print()

                db.save_message(session_id, "user", user_input)
                db.save_message(session_id, "assistant", response or "")

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
        try:
            messages = _get_session_messages(session_id)
            from alara.memory.extractor import extract_memories, summarise_session
            await extract_memories(session_id, messages, client)
            await summarise_session(session_id, messages, client)
            logger.info("Session memory and summary saved")
        except Exception as _mem_exc:
            logger.warning("Memory extraction failed: %s", _mem_exc)
        if mcp_client is not None:
            await mcp_client.disconnect()
        if session_ctx.task_queue is not None:
            session_ctx.task_queue.shutdown()


def _get_session_messages(session_id: int) -> list[dict]:
    """Return all messages for a session ordered by time, as role/content dicts."""
    return db.get_session_messages(session_id)


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
