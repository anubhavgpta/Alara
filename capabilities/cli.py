"""CLI capability for subprocess execution with exit-code verification."""

from __future__ import annotations

from alara.capabilities.base import BaseCapability
from alara.schemas.task_graph import Step, StepResult


class CLICapability(BaseCapability):
    """Execute command-line steps through subprocess orchestration."""

    def execute(self, step: Step) -> StepResult:
        """Execute a CLI step and capture process results."""
        # TODO: Implement subprocess execution, timeout, and output capture.
        pass
