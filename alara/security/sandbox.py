"""Path sandboxing for file operations.

All file operations must resolve paths through this module before accessing
the filesystem. Paths outside the configured workspace are rejected.
"""

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alara.toml"


def _get_workspace() -> Path:
    """Load and return the configured workspace path."""
    with _CONFIG_PATH.open("rb") as fh:
        config = tomllib.load(fh)
    workspace = Path(config["workspace"]["path"]).resolve()
    logger.debug("Sandbox workspace: %s", workspace)
    return workspace


def resolve_safe_path(requested: str | Path) -> Path:
    """Resolve *requested* to an absolute path and verify it is inside the workspace.

    Raises:
        PermissionError: if the resolved path is outside the allowed workspace.
    """
    workspace = _get_workspace()
    p = Path(requested).expanduser()
    # Relative paths are anchored to the workspace root, not the process CWD.
    resolved = (workspace / p).resolve() if not p.is_absolute() else p.resolve()

    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise PermissionError(
            f"Path '{resolved}' is outside the allowed workspace '{workspace}'."
        )

    # Guard against symlinks that escape the workspace.
    if resolved.is_symlink():
        real = resolved.readlink() if hasattr(resolved, "readlink") else Path(resolved).resolve()
        try:
            real.relative_to(workspace)
        except ValueError:
            raise PermissionError(
                f"Symlink '{resolved}' resolves outside the allowed workspace '{workspace}'."
            )

    logger.debug("Safe path resolved: %s", resolved)
    return resolved


def is_safe_path(requested: str | Path) -> bool:
    """Return True if *requested* resolves to a path inside the workspace."""
    try:
        resolve_safe_path(requested)
        return True
    except PermissionError:
        return False
