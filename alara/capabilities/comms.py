"""Gmail communications capability - list, read, send, and search emails."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import anyio

from rich import print as rprint
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from alara.core.errors import AlaraMCPError
from alara.security.permissions import confirm_action

if TYPE_CHECKING:
    from alara.core.gemini import GeminiClient
    from alara.core.session import SessionContext
    from alara.mcp.client import ComposioMCPClient

logger = logging.getLogger(__name__)

_LIST_PROMPT = """\
Below is raw Gmail API data. Return a JSON array where each element is an object with exactly \
these keys: from, subject, summary, action.
- from: sender name or email address
- subject: the email subject line
- summary: one-sentence plain-text summary of the email content
- action: suggested action (e.g. Reply, Archive, Read, Unsubscribe)
Do not include markdown fences or any other text - only the JSON array.

Data:
{data}
"""

_DRAFT_PROMPT = """\
Draft an email based on the following request. Return ONLY a JSON object with these keys:
  - to: recipient email address
  - subject: email subject line
  - body: full email body text

Do not include markdown fences or any other text - only the JSON object.

Request:
{request}
"""

_EXTRACT_ID_PROMPT = """\
Extract the email message ID or subject identifier from the following user request.
If a message ID (alphanumeric string like "18f2a3b4c5d6e7f8") is present, return it.
Otherwise return the subject or description text that identifies the email.
Return ONLY the identifier - no explanation, no extra text.

User request: {request}
"""

_SEARCH_QUERY_PROMPT = """\
Extract the Gmail search query from the following user request.
Return ONLY the Gmail search query string \
(e.g. "from:boss@company.com subject:meeting is:unread").
Do not include any other text.

User request: {request}
"""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from a string if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = len(lines) - 1
        while end > 0 and lines[end].strip() in ("```", ""):
            end -= 1
        text = "\n".join(lines[1 : end + 1]).strip()
    return text


async def _call_mcp(
    mcp_client: ComposioMCPClient,
    tool_name: str,
    args: dict,
) -> dict:
    """Dispatch a toolkit action via execute_tool(); raise AlaraMCPError on failure.

    execute_tool() routes through the Composio REST API (or MULTI_EXECUTE_TOOL
    fallback), which is required for GMAIL_* and other toolkit actions.
    call_tool() only works for Composio meta-tools (COMPOSIO_*) and would
    return -32602 for any real toolkit action.
    """
    try:
        return await mcp_client.execute_tool(tool_name, args)
    except AlaraMCPError:
        raise
    except Exception as exc:
        logger.error("MCP call failed for %s: %s", tool_name, exc)
        raise AlaraMCPError(f"Tool call '{tool_name}' failed: {exc}") from exc


def _build_email_table(emails: list) -> Table:
    """Build a rich.Table from a list of {from, subject, summary, action} dicts."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", min_width=3)
    table.add_column("From", min_width=20)
    table.add_column("Subject", min_width=28)
    table.add_column("Summary", min_width=38)
    table.add_column("Action?", min_width=14)
    for i, email in enumerate(emails, 1):
        table.add_row(
            str(i),
            str(email.get("from", "")),
            str(email.get("subject", "")),
            str(email.get("summary", "")),
            str(email.get("action", "")),
        )
    return table


async def _comms_list(
    user_input: str,
    session: SessionContext,
    mcp_client: ComposioMCPClient,
) -> None:
    result = await _call_mcp(
        mcp_client,
        "GMAIL_FETCH_EMAILS",
        {"maxResults": 10, "query": "is:unread"},
    )
    if result.get("status") == "error":
        rprint(f"[red]Failed to fetch emails: {' '.join(result.get('content', []))}[/red]")
        return

    raw_data = "\n".join(result.get("content", []))
    prompt = _LIST_PROMPT.format(data=raw_data)
    summary_text = session.gemini_client.chat(prompt, history=[])  # type: ignore[union-attr]

    try:
        emails = json.loads(_strip_fences(summary_text))
        if not isinstance(emails, list):
            raise ValueError("expected JSON array")
    except Exception as exc:
        logger.error("Failed to parse Gemini email summary: %s", exc)
        rprint("[red]Could not parse email summary from Gemini.[/red]")
        rprint(raw_data)
        return

    rprint(_build_email_table(emails))


def _extract_message_id(raw_content: list[str], index: int) -> str | None:
    """Return the real Gmail message ID for a 1-based list index from a fetch result."""
    combined = "\n".join(raw_content)
    try:
        parsed = json.loads(combined)
        messages = parsed.get("messages", []) if isinstance(parsed, dict) else []
        if not messages or index < 1 or index > len(messages):
            return None
        msg = messages[index - 1]
        # Composio may expose the ID under several field names.
        for field in ("messageId", "id", "message_id"):
            mid = msg.get(field)
            if mid and isinstance(mid, str) and len(mid) > 4:
                return mid
    except Exception:
        pass
    return None


async def _comms_read(
    user_input: str,
    session: SessionContext,
    mcp_client: ComposioMCPClient,
) -> None:
    prompt = _EXTRACT_ID_PROMPT.format(request=user_input)
    message_ref = session.gemini_client.chat(prompt, history=[]).strip()  # type: ignore[union-attr]

    # When Gemini returns a bare integer the user is referencing the numbered
    # row from the most recent /gmail list output.  Re-fetch the inbox to
    # resolve the index to a real Gmail message ID.
    if message_ref.isdigit():
        idx = int(message_ref)
        list_result = await _call_mcp(
            mcp_client,
            "GMAIL_FETCH_EMAILS",
            {"maxResults": max(idx, 10), "query": "is:unread"},
        )
        if list_result.get("status") != "error":
            real_id = _extract_message_id(list_result.get("content", []), idx)
            if real_id:
                message_ref = real_id
            else:
                rprint(f"[red]Could not resolve list index {idx} to a message ID.[/red]")
                return

    result = await _call_mcp(
        mcp_client,
        "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
        {"message_id": message_ref},
    )
    if result.get("status") == "error":
        rprint(f"[red]Failed to fetch email: {' '.join(result.get('content', []))}[/red]")
        return

    import json as _json
    raw_content = "\n".join(result.get("content", []))
    try:
        parsed = _json.loads(raw_content)
        subject = parsed.get("subject", "")
        sender = parsed.get("sender", "")
        timestamp = parsed.get("messageTimestamp", "")
        body_text = (
            parsed.get("messageText")
            or parsed.get("preview", {}).get("body", "")
            or raw_content
        )
        body = f"From: {sender}\nDate: {timestamp}\nSubject: {subject}\n\n{body_text}"
    except Exception:
        body = raw_content
    title = parsed.get("subject", "Email") if "parsed" in dir() else "Email"
    rprint(Panel(Markdown(body), title=title, border_style="cyan"))


async def _comms_send(
    user_input: str,
    session: SessionContext,
    mcp_client: ComposioMCPClient,
) -> None:
    prompt = _DRAFT_PROMPT.format(request=user_input)
    draft_text = session.gemini_client.chat(prompt, history=[])  # type: ignore[union-attr]

    try:
        draft = json.loads(_strip_fences(draft_text))
        if not isinstance(draft, dict):
            raise ValueError("expected JSON object")
    except Exception as exc:
        logger.error("Failed to parse Gemini email draft: %s", exc)
        rprint("[red]Could not parse email draft from Gemini.[/red]")
        return

    to: str = draft.get("to", "")
    subject: str = draft.get("subject", "")
    body: str = draft.get("body", "")
    draft_display = f"To: {to}\nSubject: {subject}\n\n{body}"
    rprint(Panel(draft_display, title="Email Draft", border_style="yellow"))

    if not confirm_action("Send this email?"):
        rprint("[dim]Send cancelled.[/dim]")
        return

    rprint("[bold red]About to send. This cannot be undone.[/bold red]")

    if not confirm_action("Confirm send?"):
        rprint("[dim]Send cancelled.[/dim]")
        return

    # Bypass execute_tool()'s generic destructive gate — both gates above already
    # provided explicit, context-rich confirmation. Call the REST path directly
    # so the user is not shown a third generic prompt.
    try:
        from alara.mcp import composio_setup
        send_args = {"recipient_email": to, "subject": subject, "body": body}
        result = await anyio.to_thread.run_sync(
            lambda: composio_setup.execute_action(
                mcp_client._api_key,
                mcp_client._user_id,
                "GMAIL_SEND_EMAIL",
                send_args,
            )
        )
    except Exception as exc:
        logger.error("GMAIL_SEND_EMAIL failed: %s", exc)
        rprint(f"[red]Failed to send email: {exc}[/red]")
        return

    if result.get("status") == "error":
        rprint(f"[red]Failed to send email: {' '.join(result.get('content', []))}[/red]")
        return

    rprint("[green]Email sent successfully.[/green]")


async def _comms_search(
    user_input: str,
    session: SessionContext,
    mcp_client: ComposioMCPClient,
) -> None:
    prompt = _SEARCH_QUERY_PROMPT.format(request=user_input)
    query = session.gemini_client.chat(prompt, history=[]).strip()  # type: ignore[union-attr]

    # GMAIL_SEARCH_EMAILS does not exist as a standalone Composio action.
    # GMAIL_FETCH_EMAILS accepts a Gmail search query via the `query` param.
    result = await _call_mcp(
        mcp_client,
        "GMAIL_FETCH_EMAILS",
        {"query": query, "maxResults": 10},
    )
    if result.get("status") == "error":
        rprint(f"[red]Failed to search emails: {' '.join(result.get('content', []))}[/red]")
        return

    raw_data = "\n".join(result.get("content", []))
    summary_prompt = _LIST_PROMPT.format(data=raw_data)
    summary_text = session.gemini_client.chat(summary_prompt, history=[])  # type: ignore[union-attr]

    try:
        emails = json.loads(_strip_fences(summary_text))
        if not isinstance(emails, list):
            raise ValueError("expected JSON array")
    except Exception as exc:
        logger.error("Failed to parse search result summary: %s", exc)
        rprint("[red]Could not parse search results.[/red]")
        rprint(raw_data)
        return

    rprint(_build_email_table(emails))


async def handle(
    intent: str,
    user_input: str,
    session: SessionContext,
    mcp_client: ComposioMCPClient | None,
) -> None:
    """Route a comms intent to the appropriate Gmail handler.

    Args:
        intent:     One of comms_list, comms_read, comms_send, comms_search.
        user_input: Original user message (or full /gmail command string).
        session:    Current SessionContext carrying gemini_client.
        mcp_client: Active ComposioMCPClient; None if Composio is unavailable.
    """
    if mcp_client is None:
        rprint("[red]Gmail tools require an active Composio connection.[/red]")
        return
    if session.gemini_client is None:
        rprint("[red]Gmail tools require the Gemini client to be initialised.[/red]")
        return

    try:
        if intent == "comms_list":
            await _comms_list(user_input, session, mcp_client)
        elif intent == "comms_read":
            await _comms_read(user_input, session, mcp_client)
        elif intent == "comms_send":
            await _comms_send(user_input, session, mcp_client)
        elif intent == "comms_search":
            await _comms_search(user_input, session, mcp_client)
        else:
            logger.warning("comms.handle received unknown intent: %s", intent)
    except AlaraMCPError as exc:
        logger.error("comms MCP error for intent %s: %s", intent, exc)
        rprint(f"[red]{exc}[/red]")
