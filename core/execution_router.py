"""Execution routing module for dispatching steps across capability layers."""

from __future__ import annotations

from alara.schemas.task_graph import Step, StepResult


class ExecutionRouter:
    """Route plan steps to the best available capability implementation."""

    def execute_step(self, step: Step) -> StepResult:
        """Execute a single step using the capability hierarchy."""
        # TODO: Implement capability routing and execution.
        pass
