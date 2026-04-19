"""Background scheduler for proactive watcher execution."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import schedule

from alara.watchers import store
from alara.watchers.models import Watcher

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession
    from alara.core.session import SessionContext
    from alara.core.gemini import GeminiClient

logger = logging.getLogger(__name__)


def parse_natural_schedule(description: str, gemini_client: "GeminiClient") -> str:
    """Convert a natural-language schedule description to a cron expression."""
    system = (
        "Convert this schedule description to a cron expression. "
        "Reply with ONLY the cron expression (5 fields), nothing else. "
        "Examples: 'every morning at 9am' -> '0 9 * * *', "
        "'every hour' -> '0 * * * *', 'daily at midnight' -> '0 0 * * *'"
    )
    try:
        raw = gemini_client.chat(f"{system}\n\n{description}", history=[]).strip()
        parts = raw.split()
        if len(parts) == 5:
            return raw
        logger.warning("Gemini returned non-cron response for schedule %r: %r", description, raw)
    except Exception as exc:
        logger.warning("parse_natural_schedule failed: %s", exc)
    return "0 9 * * *"


def _run_watcher(
    watcher: Watcher,
    session: "SessionContext",
    pt_app: "PromptSession",
) -> None:
    """Execute one watcher: run tool or Gemini, summarise, save, surface."""
    import asyncio
    from prompt_toolkit import print_formatted_text
    from prompt_toolkit.formatted_text import FormattedText

    try:
        result_text: str = ""

        if watcher.tool and session.mcp_client is not None:
            try:
                loop = asyncio.new_event_loop()
                raw = loop.run_until_complete(
                    session.mcp_client.execute_tool(
                        watcher.tool,
                        watcher.params or {},
                    )
                )
                loop.close()
                content = raw.get("content", [])
                result_text = "\n".join(content) if content else "No result."
            except Exception as exc:
                logger.warning("Watcher %d tool execution failed: %s", watcher.id, exc)
                result_text = f"Tool execution failed: {exc}"
        else:
            if session.gemini_client is not None:
                try:
                    result_text = session.gemini_client.chat(
                        watcher.description,
                        history=[],
                    )
                except Exception as exc:
                    logger.warning("Watcher %d Gemini call failed: %s", watcher.id, exc)
                    result_text = f"Gemini call failed: {exc}"
            else:
                result_text = "No tool or Gemini client available."

        summary = result_text[:200]
        if session.gemini_client is not None:
            try:
                summary = session.gemini_client.chat(
                    f"Summarise the following in one sentence:\n\n{result_text[:2000]}",
                    history=[],
                ).strip()
            except Exception as exc:
                logger.warning("Watcher %d summary generation failed: %s", watcher.id, exc)

        store.save_watcher_result(watcher.id, result_text, summary)
        store.update_watcher_run(watcher.id, summary)

        print_formatted_text(
            FormattedText([
                ("class:watcher", f"[Watcher: {watcher.description}] "),
                ("", summary),
            ]),
            file=pt_app.output,
        )
        logger.info("Watcher %d executed successfully", watcher.id)

    except Exception as exc:
        logger.warning("Watcher %d raised unexpected error: %s", watcher.id, exc)


def _cron_to_time(cron_expr: str) -> str:
    """Extract HH:MM from the minute/hour fields of a cron expression."""
    parts = cron_expr.split()
    if len(parts) < 2:
        return "09:00"
    minute = parts[0] if parts[0].isdigit() else "0"
    hour = parts[1] if parts[1].isdigit() else "9"
    return f"{int(hour):02d}:{int(minute):02d}"


def register_watcher(
    watcher: Watcher,
    session: "SessionContext",
    pt_app: "PromptSession",
) -> None:
    """Register a single watcher into the live schedule."""
    time_str = _cron_to_time(watcher.schedule)
    schedule.every().day.at(time_str).do(
        _run_watcher, watcher, session, pt_app
    ).tag(f"watcher-{watcher.id}")
    logger.info(
        "Registered watcher id=%d description=%r at %s",
        watcher.id, watcher.description, time_str,
    )


def register_all_watchers(
    session: "SessionContext",
    pt_app: "PromptSession",
) -> None:
    """Load all active watchers from DB and schedule them."""
    watchers = store.get_all_watchers()
    active = [w for w in watchers if w.status == "active"]
    for watcher in active:
        register_watcher(watcher, session, pt_app)
    logger.info("Registered %d watchers", len(active))


def start_scheduler(
    session: "SessionContext",
    pt_app: "PromptSession",
) -> threading.Thread:
    """Start the background scheduler daemon thread."""

    def _loop() -> None:
        logger.info("Watcher scheduler started")
        while True:
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.warning("Scheduler loop error: %s", exc)
            time.sleep(60)

    thread = threading.Thread(target=_loop, name="alara-scheduler", daemon=True)
    thread.start()
    return thread
