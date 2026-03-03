"""Filesystem capability for file and folder operations via pathlib."""

from __future__ import annotations

from pathlib import Path

from alara.capabilities.base import BaseCapability
from alara.schemas.task_graph import Step, StepResult


class FilesystemCapability(BaseCapability):
    """Execute filesystem-focused steps using pathlib-based operations."""

    def execute(self, step: Step) -> StepResult:
        """Execute a filesystem step."""
        # TODO: Implement safe file and directory operations.
        pass

    def resolve_path(self, raw_path: str) -> Path:
        """Resolve user-provided paths into absolute Path objects."""
        # TODO: Implement robust Windows-aware path normalization.
        pass
