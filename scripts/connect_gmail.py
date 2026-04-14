"""One-time Gmail OAuth connection script for Alara.

Run this script once to authorise Gmail access via Composio.
After completion, Alara will be able to read, search, and send email.

Usage:
    python scripts/connect_gmail.py
"""

import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.status import Status

# Ensure the project root is on sys.path so `alara` imports resolve whether
# the package is installed or the script is run directly from the repo.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from alara.security.vault import get_secret  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

_console = Console()

_POLL_INTERVAL_SECONDS: int = 3
_TIMEOUT_SECONDS: int = 120
_TOOLKIT: str = "gmail"


def _read_credentials() -> tuple[str, str] | tuple[None, None]:
    """Read Composio credentials from the OS keyring.

    Returns (api_key, user_id) on success, or (None, None) if either is missing.
    """
    api_key: str | None = get_secret("composio_api_key")
    user_id: str | None = get_secret("composio_user_id")

    if not api_key or not user_id:
        missing = []
        if not api_key:
            missing.append("composio_api_key")
        if not user_id:
            missing.append("composio_user_id")
        _console.print(
            f"[red]Missing keyring credential(s): {', '.join(missing)}.[/red]\n"
            "Run [bold]alara[/bold] first to complete the Composio setup wizard, "
            "then re-run this script."
        )
        return None, None

    return api_key, user_id


def _check_active_connection(client: object, user_id: str) -> bool:
    """Return True if the user already has an active Gmail connection.

    Uses server-side filtering so no client-side attribute inspection is needed.
    """
    response = client.connected_accounts.list(  # type: ignore[attr-defined]
        user_ids=[user_id],
        toolkit_slugs=[_TOOLKIT],
        statuses=["ACTIVE"],
    )
    return bool(getattr(response, "items", []))


def main() -> None:
    """Entry point — orchestrates the full Gmail OAuth flow."""
    api_key, user_id = _read_credentials()
    if api_key is None or user_id is None:
        return

    try:
        from composio import Composio  # type: ignore[import-untyped]
    except ImportError:
        _console.print(
            "[red]The [bold]composio[/bold] package is not installed.\n"
            "Run: [bold]pip install composio[/bold][/red]"
        )
        logger.error("composio package not found")
        return

    # ------------------------------------------------------------------
    # 1. Initialise Composio client
    # ------------------------------------------------------------------
    try:
        client = Composio(api_key=api_key)
    except Exception as exc:
        logger.error("Failed to initialise Composio client: %s", exc)
        _console.print(
            f"[red]Could not initialise the Composio client: {exc}[/red]\n"
            "Check that your API key is valid."
        )
        return

    # ------------------------------------------------------------------
    # 2. Check for an existing active Gmail connection
    # ------------------------------------------------------------------
    try:
        if _check_active_connection(client, user_id):
            _console.print("[green]Gmail is already connected.[/green]")
            return
    except Exception as exc:
        logger.error("Could not list connected accounts: %s", exc)
        _console.print(
            f"[red]Failed to check existing connections: {exc}[/red]"
        )
        return

    # ------------------------------------------------------------------
    # 3. Initiate a new OAuth flow
    #    client.toolkits.authorize() is the public helper that
    #    automatically finds or creates the Composio-managed auth config
    #    for the toolkit and calls connected_accounts.initiate() internally.
    # ------------------------------------------------------------------
    try:
        request = client.toolkits.authorize(user_id=user_id, toolkit=_TOOLKIT)
    except Exception as exc:
        logger.error("Failed to initiate Gmail OAuth: %s", exc)
        _console.print(
            f"[red]Could not start the Gmail OAuth flow: {exc}[/red]\n"
            "Verify your Composio credentials and try again."
        )
        return

    redirect_url: str = getattr(request, "redirect_url", None) or ""
    if not redirect_url:
        logger.error("Composio returned no redirect URL; response: %s", request)
        _console.print(
            "[red]Composio did not return a redirect URL. "
            "This may be a temporary API issue — please try again.[/red]"
        )
        return

    _console.print()
    _console.print("[cyan]Open this URL in your browser to connect Gmail:[/cyan]")
    _console.print(f"[link]{redirect_url}[/link]")
    _console.print()

    # ------------------------------------------------------------------
    # 4. Poll for OAuth completion
    #    Re-queries connected_accounts.list() with server-side filters
    #    every _POLL_INTERVAL_SECONDS until the connection is ACTIVE or
    #    _TIMEOUT_SECONDS has elapsed.
    # ------------------------------------------------------------------
    deadline: float = time.monotonic() + _TIMEOUT_SECONDS
    connected: bool = False

    with Status(
        "Waiting for Gmail OAuth to complete...",
        console=_console,
        spinner="dots",
    ) as status:
        while time.monotonic() < deadline:
            time.sleep(_POLL_INTERVAL_SECONDS)
            try:
                if _check_active_connection(client, user_id):
                    connected = True
                    break
            except Exception as exc:
                logger.warning("Poll error (will retry): %s", exc)
                status.update(f"[yellow]Poll error — retrying... ({exc})[/yellow]")

    if not connected:
        _console.print(
            "[red]Timed out waiting for Gmail authorisation. "
            "Re-run this script to try again.[/red]"
        )
        logger.warning(
            "Gmail OAuth polling timed out after %d seconds", _TIMEOUT_SECONDS
        )
        return

    _console.print("[green]Gmail connected successfully.[/green]")
    logger.info("Gmail OAuth connection confirmed for user_id=%s", user_id)

    # ------------------------------------------------------------------
    # 5. Verify tools are available by creating a test session
    # ------------------------------------------------------------------
    try:
        session = client.create(user_id=user_id, toolkits=[_TOOLKIT])
        mcp_url: str = session.mcp.url
    except Exception as exc:
        logger.error("Failed to create verification session: %s", exc)
        _console.print(
            f"[red]Gmail is authorised but a test session could not be created: {exc}[/red]\n"
            "This may resolve itself — try running [bold]alara[/bold]."
        )
        return

    _console.print()
    _console.print(f"[dim]MCP endpoint: {mcp_url}[/dim]")
    _console.print("[green]Alara is ready to use Gmail. Run: alara[/green]")
    _console.print()


if __name__ == "__main__":
    main()
