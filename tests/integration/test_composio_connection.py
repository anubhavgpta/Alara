"""
Manual integration test — requires real COMPOSIO_API_KEY and COMPOSIO_USER_ID.
Run with: python tests/integration/test_composio_connection.py
"""
import asyncio
import sys
from pathlib import Path

# Make the project root importable when run directly from the repo.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import keyring
from rich import print as rprint
from alara.mcp.composio_setup import create_session
from alara.mcp.client import ComposioMCPClient
from alara.mcp.registry import MCPRegistry

async def main() -> None:
    api_key = keyring.get_password("alara", "composio_api_key")
    user_id = keyring.get_password("alara", "composio_user_id")

    if not api_key or not user_id:
        rprint("[red]Missing composio_api_key or composio_user_id in keyring.")
        rprint("Run `alara --setup` first.[/red]")
        return

    rprint("[cyan]Step 1: Creating Composio session...[/cyan]")
    mcp_url = create_session(api_key, user_id, toolkits=["gmail"])
    rprint("[green]Session created.[/green]")

    rprint("[cyan]Step 2: Connecting MCP client...[/cyan]")
    async with ComposioMCPClient(mcp_url, api_key) as client:
        rprint("[green]Connected.[/green]")

        rprint("[cyan]Step 3: Listing tools...[/cyan]")
        tools = await client.list_tools()
        rprint(f"[green]{len(tools)} tools discovered.[/green]")
        for t in tools[:5]:
            rprint(f"  - {t['name']}: {t['description'][:60]}")

        rprint("[cyan]Step 4: Loading registry...[/cyan]")
        registry = MCPRegistry()
        registry.load(tools)
        rprint(f"Toolkits found: {registry.available_toolkits()}")

        rprint("[cyan]Step 5: Calling GMAIL_FETCH_EMAILS (read-only)...[/cyan]")
        result = await client.call_tool("GMAIL_FETCH_EMAILS", {"max_results": 3})
        rprint(f"[green]Got result:[/green] {str(result)[:200]}")

    rprint("[bold green]All integration checks passed.[/bold green]")

asyncio.run(main())
