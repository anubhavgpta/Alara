"""Dynamic MCP service discovery — builds a ToolManifest registry from connected servers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)

_DESTRUCTIVE_VERBS_RE = re.compile(
    r"(create|delete|send|update|modify|patch|remove|write|post)",
    re.IGNORECASE,
)


@dataclass
class ToolManifest:
    name: str
    description: str
    input_schema: dict
    is_destructive: bool
    service: str


@dataclass
class ServiceRegistry:
    services: dict[str, dict[str, ToolManifest]] = field(default_factory=dict)


async def _get_slugs(session: "SessionContext", api_key: str, user_id: str) -> list[str]:
    """Return the toolkit slugs to discover tools for.

    Primary: session.active_toolkits (populated at startup from user's
    toolkit selection — no extra network call needed).
    Fallback: query Composio for all ACTIVE connected accounts dynamically.
    No hardcoded lists anywhere.
    """
    import anyio
    from alara.mcp import composio_setup

    if session.active_toolkits:
        logger.debug(
            "discover_services: using cached active_toolkits=%s", session.active_toolkits
        )
        return list(session.active_toolkits)

    logger.debug(
        "discover_services: active_toolkits empty — querying Composio for connected slugs"
    )
    slugs: list[str] = await anyio.to_thread.run_sync(
        lambda: composio_setup.get_all_connected_slugs(api_key, user_id)
    )
    return slugs


async def discover_services(session: "SessionContext") -> ServiceRegistry:
    """Discover real app tools via the Composio REST API and build a ServiceRegistry.

    Steps:
      1. Call list_tools() only to verify the MCP session is alive.
         COMPOSIO_* meta-tools are never added to the registry.
      2. Derive the toolkit slug list from session.active_toolkits (cached,
         no extra network call) or fall back to a live query of all ACTIVE
         connected accounts.  No hardcoded slug lists.
      3. For each slug, fetch real tool schemas via composio_setup.get_toolkit_tools().
         Per-slug failures are logged as warnings and skipped — never raised.
      4. Build ToolManifest per tool and populate the registry.

    Stores the result in session.service_registry and returns it.
    """
    import anyio
    from alara.mcp import composio_setup
    from alara.security import vault

    registry = ServiceRegistry()

    if session.mcp_client is None:
        logger.info("discover_services: no MCP client available")
        return registry

    # Step 1: Verify MCP session is alive
    try:
        await session.mcp_client.list_tools()
    except Exception as exc:
        logger.warning("discover_services: MCP session check failed: %s", exc)
        return registry

    # Step 2: Resolve credentials and slug list
    api_key: str = vault.get_secret("composio_api_key") or ""
    user_id: str = vault.get_secret("composio_user_id") or ""

    if not api_key:
        logger.warning("discover_services: Composio API key unavailable — skipping discovery")
        return registry

    slugs = await _get_slugs(session, api_key, user_id)
    if not slugs:
        logger.warning("discover_services: no connected app slugs found — skipping discovery")
        return registry

    # Step 3 + 4: Fetch and parse tools per slug
    for slug in slugs:
        try:
            tools: list[dict] = await anyio.to_thread.run_sync(
                lambda s=slug: composio_setup.get_toolkit_tools(api_key, s)
            )
            logger.debug(
                "discover_services: slug='%s' returned %d tools", slug, len(tools)
            )
            if not tools:
                continue

            for tool in tools:
                name: str = tool.get("name", "")
                if not name:
                    continue
                description: str = tool.get("description", "")
                input_schema: dict = tool.get("inputSchema", {}) or {}
                service: str = (tool.get("toolkit") or slug).lower()
                is_destructive = bool(_DESTRUCTIVE_VERBS_RE.search(name))

                manifest = ToolManifest(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    is_destructive=is_destructive,
                    service=service,
                )
                if service not in registry.services:
                    registry.services[service] = {}
                registry.services[service][name] = manifest

        except Exception as exc:
            logger.warning("discover_services: failed for slug '%s': %s", slug, exc)

    n_tools = sum(len(v) for v in registry.services.values())
    n_services = len(registry.services)
    logger.info("Discovered %d tools across %d services", n_tools, n_services)
    logger.debug(
        "discover_services: services found: %s", list(registry.services.keys())
    )

    session.service_registry = registry
    return registry


def get_tool(registry: ServiceRegistry, service: str, tool: str) -> ToolManifest | None:
    """Return the ToolManifest for (service, tool) or None if not found."""
    return registry.services.get(service, {}).get(tool)


def all_tools_flat(registry: ServiceRegistry) -> list[ToolManifest]:
    """Return all ToolManifests as a flat list across all services."""
    result: list[ToolManifest] = []
    for tools in registry.services.values():
        result.extend(tools.values())
    return result
