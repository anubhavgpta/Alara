"""Planning module for converting goal context into a task graph via Gemini."""

from __future__ import annotations

from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import TaskGraph


class Planner:
    """Generate a task graph from a parsed GoalContext."""

    def plan(self, goal: GoalContext) -> TaskGraph:
        """Produce an executable task graph for the given goal context."""
        # TODO: Implement Gemini-backed planning.
        pass
