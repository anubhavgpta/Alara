"""File I/O capability with sandbox enforcement."""

import logging
from pathlib import Path

from alara.security import permissions, sandbox

logger = logging.getLogger(__name__)


def read_file(path: str) -> str:
    """Read and return the contents of a sandboxed file.

    Args:
        path: Path to the file (relative to workspace or absolute).

    Returns:
        File contents as a string, or an error message.
    """
    try:
        safe = sandbox.resolve_safe_path(path)
        logger.debug("Reading file: %s", safe)
        return safe.read_text(encoding="utf-8")
    except PermissionError as exc:
        logger.warning("File read denied: %s", exc)
        return f"Permission denied: {exc}"
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return f"File not found: {path}"
    except Exception as exc:
        logger.exception("Unexpected error reading file: %s", path)
        return f"Error reading file: {exc}"


def write_file(path: str, content: str) -> str:
    """Write content to a sandboxed file after user confirmation.

    Args:
        path: Destination file path (relative to workspace or absolute).
        content: Text content to write.

    Returns:
        A confirmation or cancellation message.
    """
    if not permissions.confirm_action(f"Write to file: {path}"):
        logger.debug("File write cancelled: %s", path)
        return "Write cancelled."

    try:
        safe = sandbox.resolve_safe_path(path)
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        logger.debug("File written: %s", safe)
        return f"Written: {path}"
    except PermissionError as exc:
        logger.warning("File write denied: %s", exc)
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error writing file: %s", path)
        return f"Error writing file: {exc}"


def list_files(directory: str = "") -> str:
    """List files and subdirectories in a sandboxed directory.

    Args:
        directory: Directory path to list. Defaults to workspace root if empty.

    Returns:
        A formatted string listing directory contents, or an error message.
    """
    try:
        target = directory if directory else ""
        if not target:
            import tomllib
            config_path = Path(__file__).parent.parent.parent / "config" / "alara.toml"
            with config_path.open("rb") as fh:
                config = tomllib.load(fh)
            target = config["workspace"]["path"]

        safe = sandbox.resolve_safe_path(target)
        logger.debug("Listing directory: %s", safe)

        if not safe.exists():
            return f"Directory not found: {target}"
        if not safe.is_dir():
            return f"Not a directory: {target}"

        entries = sorted(safe.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            return f"Directory is empty: {safe}"

        lines = [f"Contents of {safe}:", ""]
        for entry in entries:
            if entry.is_dir():
                lines.append(f"  [dir]  {entry.name}/")
            else:
                size = entry.stat().st_size
                lines.append(f"  [file] {entry.name}  ({size} bytes)")

        return "\n".join(lines)

    except PermissionError as exc:
        logger.warning("Directory listing denied: %s", exc)
        return f"Permission denied: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error listing directory: %s", directory)
        return f"Error listing directory: {exc}"
