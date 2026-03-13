"""Platform helper functions for OS detection and path resolution."""

from __future__ import annotations

from pathlib import Path
from loguru import logger


def detect_platform() -> str:
    """Return normalized platform identifier for runtime host."""
    import sys
    if sys.platform.startswith('win'):
        return 'windows'
    elif sys.platform.startswith('darwin'):
        return 'macos'
    else:
        return 'linux'


def resolve_user_path(raw_path: str) -> Path:
    """Resolve user-provided paths into normalized absolute Paths."""
    try:
        # Step 1 — Handle None or empty string
        if raw_path is None or raw_path.strip() == "":
            return Path.cwd()

        # Step 2 — Substitute known environment variable patterns
        path_string = str(raw_path)
        path_string = path_string.replace("$env:USERPROFILE", str(Path.home()))
        path_string = path_string.replace("%USERPROFILE%", str(Path.home()))
        path_string = path_string.replace("$env:HOME", str(Path.home()))
        path_string = path_string.replace("$HOME", str(Path.home()))
        
        # Step 3 — Expand any remaining ~ using pathlib
        result = Path(path_string).expanduser()

        # Step 4 — Anchor relative paths to home directory
        if result.is_absolute():
            return result
        else:
            return Path.home() / result

    except Exception as exc:
        logger.warning("Path resolution failed for '{}': {}", raw_path, exc)
        return Path.home()