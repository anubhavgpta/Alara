"""Session memory model for in-memory execution history and runtime state."""

from __future__ import annotations

from alara.schemas.task_graph import StepResult


class SessionMemory:
    """Track current session state and step execution history."""

    def start_session(self, goal: str) -> None:
        """Initialize a new session for the provided goal."""
        # TODO: Implement session lifecycle state management.
        pass

    def record_step_result(self, result: StepResult) -> None:
        """Append a step result to current session history."""
        # TODO: Implement execution history persistence for active session.
        pass
