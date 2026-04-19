"""Composio session creation and connection-status helpers."""

import logging

from alara.core.errors import AlaraConfigError, AlaraMCPError

logger = logging.getLogger(__name__)


def _resolve_connected_accounts(
    client: object,
    user_id: str,
    toolkits: list[str],
) -> dict[str, str]:
    """Return a {toolkit_slug: connected_account_id} map for active connections.

    Queries all configured toolkits in one batched REST call.  Toolkits that
    have no active connection are omitted — the caller passes only the resolved
    entries to session.create(), which is sufficient for the Tool Router to bind
    the right accounts.

    Errors are swallowed and logged at DEBUG level; an empty dict is returned
    so the caller can still attempt session creation without explicit bindings.

    Args:
        client:   composio_client.Composio instance.
        user_id:  Composio entity / user identifier.
        toolkits: Toolkit slugs to resolve (e.g. ["gmail", "slack"]).
    """
    result: dict[str, str] = {}
    try:
        response = client.connected_accounts.list(  # type: ignore[attr-defined]
            user_ids=[user_id],
            toolkit_slugs=toolkits,
            statuses=["ACTIVE"],
        )
        for item in response.items:
            slug: str = (getattr(item.toolkit, "slug", None) or "").lower()
            account_id: str | None = getattr(item, "id", None)
            if slug and account_id and slug in [t.lower() for t in toolkits]:
                if slug not in result:
                    result[slug] = account_id
                    logger.debug(
                        "Resolved connected_account: toolkit=%s id=%s",
                        slug, account_id,
                    )
    except Exception as exc:
        logger.debug("Could not resolve connected_accounts: %s", exc)
    return result


def create_session(api_key: str, user_id: str, toolkits: list[str]) -> str:
    """Create a Composio Tool Router session and return its MCP URL.

    The URL is scoped to *user_id* and grants access to all listed *toolkits*.
    Composio manages OAuth, token refresh, and per-service auth for every
    toolkit — Alara never touches service credentials directly.

    Active connected account IDs are resolved before calling session.create()
    and passed via the ``connected_accounts`` parameter.  This serves two
    purposes:

    1. It overrides the Tool Router's default connection lookup, ensuring the
       session uses the current authenticated account for each toolkit rather
       than a cached or mismatched one.
    2. The resolved IDs are part of the POST body, so the Composio backend
       generates a distinct session URL when connection state has changed —
       preventing stale sessions (created before a toolkit was authenticated)
       from persisting across restarts.

    Args:
        api_key:  Composio API key from the OS keyring.
        user_id:  Stable identifier for the end user (e.g. email address).
        toolkits: List of toolkit names to activate (e.g. ["gmail", "slack"]).

    Returns:
        The streamable-HTTP MCP URL for the new session.

    Raises:
        AlaraConfigError: If api_key or user_id are missing.
        AlaraMCPError:    On any Composio SDK error.
    """
    if not api_key:
        raise AlaraConfigError(
            "Composio API key is missing. Run `alara` to complete setup, "
            "or re-run the setup wizard."
        )
    if not user_id:
        raise AlaraConfigError(
            "Composio user ID is missing. Run `alara` to complete setup, "
            "or re-run the setup wizard."
        )

    try:
        from composio_client import Composio  # type: ignore[import]

        client = Composio(api_key=api_key)

        connected: dict[str, str] = _resolve_connected_accounts(
            client, user_id, toolkits
        )
        logger.debug("Connected accounts resolved: %s", list(connected.keys()))

        create_kwargs: dict = {
            "user_id": user_id,
            "toolkits": {"enable": toolkits},
        }
        if connected:
            create_kwargs["connected_accounts"] = connected

        response = client.tool_router.session.create(**create_kwargs)
        url: str = response.mcp.url
        logger.debug(
            "Composio MCP URL obtained for user_id=%s toolkits=%s",
            user_id, toolkits,
        )
        return url
    except (AlaraConfigError, AlaraMCPError):
        raise
    except Exception as exc:
        raise AlaraMCPError(
            f"Failed to create Composio Tool Router session: {exc}"
        ) from exc


def get_toolkit_tools(api_key: str, toolkit: str) -> list[dict]:
    """Return all tools for *toolkit* as a list of normalised dicts.

    Fetches tool metadata from the Composio REST API (not MCP) so the results
    contain real toolkit-specific tool slugs (e.g. GMAIL_FETCH_EMAILS) rather
    than the generic meta-tools returned by the MCP list_tools endpoint.

    Each dict has keys: name, description, toolkit, inputSchema.

    Errors are swallowed and logged at DEBUG level; an empty list is returned
    so callers degrade gracefully without crashing startup.

    Args:
        api_key:  Composio API key.
        toolkit:  Lowercase toolkit name (e.g. "gmail").
    """
    try:
        from composio_client import Composio  # type: ignore[import]

        client = Composio(api_key=api_key)
        tools: list[dict] = []
        cursor: str | None = None

        while True:
            kwargs: dict = {"toolkit_slug": toolkit.lower(), "limit": 50}
            if cursor:
                kwargs["cursor"] = cursor

            result = client.tools.list(**kwargs)
            for t in result.items:
                tools.append(
                    {
                        "name": getattr(t, "slug", "") or "",
                        "description": getattr(t, "description", "") or "",
                        "toolkit": toolkit.lower(),
                        "inputSchema": getattr(t, "input_parameters", {}) or {},
                    }
                )

            cursor = getattr(result, "next_cursor", None)
            if not cursor:
                break

        logger.debug(
            "get_toolkit_tools: toolkit=%s fetched=%d", toolkit, len(tools)
        )
        return tools
    except Exception as exc:
        logger.debug("Could not fetch tools for toolkit '%s': %s", toolkit, exc)
        return []


def execute_action(api_key: str, user_id: str, tool_slug: str, args: dict) -> dict:
    """Execute a toolkit action via ComposioToolSet REST API (full response, not preview-truncated).

    The MCP Tool Router only returns ``data_preview`` in its response, which
    Composio truncates to avoid overwhelming LLM context windows.
    ComposioToolSet.execute_action() calls the REST API directly and returns
    the full payload.

    Args:
        api_key:   Composio API key.
        user_id:   Composio entity ID (user).
        tool_slug: Toolkit action slug (e.g. "GMAIL_FETCH_EMAILS").
        args:      Arguments matching the tool's inputSchema.

    Returns:
        {"status": "ok"|"error", "content": list[str]}

    Raises:
        AlaraMCPError: On SDK or API failure.
    """
    import json

    try:
        try:
            from composio import ComposioToolSet  # type: ignore[import]
        except ImportError:
            from composio.tools.toolset import ComposioToolSet  # type: ignore[import]

        toolset = ComposioToolSet(api_key=api_key, entity_id=user_id)
        result = toolset.execute_action(
            action=tool_slug,
            params=args,
            entity_id=user_id,
        )
        logger.debug(
            "execute_action REST: tool=%s result_keys=%s",
            tool_slug,
            list(result.keys()) if isinstance(result, dict) else type(result),
        )
        if isinstance(result, dict) and "successful" in result:
            successful: bool = bool(result.get("successful", False))
            data: dict = result.get("data") or {}
        else:
            successful = True
            data = result or {}
        return {
            "status": "ok" if successful else "error",
            "content": [json.dumps(data)],
        }
    except Exception as exc:
        raise AlaraMCPError(
            f"ComposioToolSet.execute_action('{tool_slug}') failed: {exc}"
        ) from exc


def get_all_connected_slugs(api_key: str, user_id: str) -> list[str]:
    """Return all toolkit slugs with an active Composio connection for *user_id*.

    Queries connected_accounts without a pre-specified toolkit list so the
    result is fully dynamic — any newly connected app will appear automatically.

    Errors are swallowed and logged at DEBUG level; an empty list is returned
    so callers degrade gracefully.

    Args:
        api_key:  Composio API key.
        user_id:  Composio entity / user identifier.
    """
    try:
        from composio_client import Composio  # type: ignore[import]

        client = Composio(api_key=api_key)
        response = client.connected_accounts.list(
            user_ids=[user_id],
            statuses=["ACTIVE", "INITIATED"],
        )
        slugs: list[str] = []
        seen: set[str] = set()
        for item in response.items:
            slug: str = (getattr(item.toolkit, "slug", None) or "").lower()
            if slug and slug not in seen:
                slugs.append(slug)
                seen.add(slug)
        logger.debug("get_all_connected_slugs: user=%s slugs=%s", user_id, slugs)
        return slugs
    except Exception as exc:
        logger.debug("Could not fetch connected slugs for user '%s': %s", user_id, exc)
        return []


def get_connection_status(api_key: str, user_id: str, toolkit: str) -> bool:
    """Return True if *user_id* has an active Composio connection for *toolkit*.

    A False result means the user needs to run the connect script (e.g.
    scripts/connect_gmail.py) to authorise the service.  Errors during the
    check are logged and treated as not-connected rather than propagated.

    Args:
        api_key:  Composio API key.
        user_id:  Composio entity / user identifier.
        toolkit:  Lowercase toolkit name (e.g. "gmail").
    """
    try:
        from composio_client import Composio  # type: ignore[import]

        client = Composio(api_key=api_key)
        response = client.connected_accounts.list(
            user_ids=[user_id],
            toolkit_slugs=[toolkit.lower()],
            statuses=["ACTIVE", "INITIATED"],
        )
        return bool(response.items)
    except Exception as exc:
        logger.debug(
            "Could not check Composio connection status for toolkit '%s': %s",
            toolkit, exc,
        )
        return False
