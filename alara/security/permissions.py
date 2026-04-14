"""User-facing permission gate for sensitive actions."""

import logging

from rich.console import Console
from rich.text import Text

logger = logging.getLogger(__name__)
_console = Console(stderr=False)


def confirm_action(action_description: str) -> bool:
    """Display an amber-styled action description and ask the user to confirm.

    Returns True only if the user explicitly types 'y' or 'yes'.
    Defaults to False on empty input or any other response.
    Never raises.
    """
    try:
        label = Text("Permission required: ", style="bold yellow")
        label.append(action_description, style="yellow")
        _console.print(label)

        response = input("Allow this action? [y/N]: ").strip().lower()
        allowed = response in ("y", "yes")
        logger.debug(
            "Permission gate: action=%r allowed=%s", action_description, allowed
        )
        return allowed
    except Exception as exc:
        logger.warning("Permission gate failed unexpectedly: %s", exc)
        return False
