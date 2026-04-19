from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from rich import print as rprint

logger = logging.getLogger(__name__)


@dataclass
class CapabilityEntry:
    name: str
    intents: list[str]
    is_destructive: bool
    handler: Callable


# ---------------------------------------------------------------------------
# Per-capability sync handlers (safe to call from ThreadPoolExecutor threads)
# Async capability handlers are wrapped with asyncio.run(), which works in
# worker threads because they carry no pre-existing event loop.
# ---------------------------------------------------------------------------

def _research_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import research as research_mod
    result = research_mod.research(user_input, session.gemini_client)
    rprint(result)


def _files_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import files as files_mod
    result = files_mod.read_file(user_input)
    rprint(result)


def _writing_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import writing as writing_mod
    result = writing_mod.draft(user_input, session.gemini_client)
    rprint(result)


def _coding_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import coding as coding_mod
    asyncio.run(
        coding_mod.handle(intent, user_input, session, session.gemini_client, {})
    )


def _comms_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import comms as comms_mod
    asyncio.run(comms_mod.handle(intent, user_input, session, session.mcp_client))


def _tasks_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities import task_manager as tasks_mod
    asyncio.run(
        tasks_mod.handle(intent, user_input, session, session.task_queue)
    )


def _generic_chat_handler(intent: str, user_input: str, session) -> None:
    result = session.gemini_client.chat(user_input, history=[])
    rprint(result)


def _generic_mcp_handler(intent: str, user_input: str, session) -> None:
    from alara.capabilities.generic_mcp import handle as generic_mcp_handle
    tool_name = session.pending_mcp_tool or ""
    session.pending_mcp_tool = None
    if tool_name:
        asyncio.run(generic_mcp_handle(tool_name, user_input, session))


def get_registry() -> dict[str, CapabilityEntry]:
    return {
        "research": CapabilityEntry(
            name="research",
            intents=["research_submit"],
            is_destructive=False,
            handler=_research_handler,
        ),
        "files": CapabilityEntry(
            name="files",
            intents=["file_read", "file_write"],
            is_destructive=True,
            handler=_files_handler,
        ),
        "writing": CapabilityEntry(
            name="writing",
            intents=["write_draft"],
            is_destructive=False,
            handler=_writing_handler,
        ),
        "coding": CapabilityEntry(
            name="coding",
            intents=["code_write", "code_fix", "code_review"],
            is_destructive=True,
            handler=_coding_handler,
        ),
        "comms": CapabilityEntry(
            name="comms",
            intents=["comms_send"],
            is_destructive=True,
            handler=_comms_handler,
        ),
        "tasks": CapabilityEntry(
            name="tasks",
            intents=["research_submit"],
            is_destructive=False,
            handler=_tasks_handler,
        ),
        "generic_chat": CapabilityEntry(
            name="generic_chat",
            intents=[],
            is_destructive=False,
            handler=_generic_chat_handler,
        ),
        "generic_mcp": CapabilityEntry(
            name="generic_mcp",
            intents=[],
            is_destructive=False,
            handler=_generic_mcp_handler,
        ),
    }


def valid_capability_names() -> list[str]:
    return [
        "research",
        "files",
        "writing",
        "coding",
        "comms",
        "tasks",
        "generic_chat",
        "generic_mcp",
    ]
