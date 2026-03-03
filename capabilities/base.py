"""Abstract base capability contract used by all execution capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod

from alara.schemas.task_graph import Step, StepResult


class BaseCapability(ABC):
    """Base class for all capabilities that execute a plan step."""

    @abstractmethod
    def execute(self, step: Step) -> StepResult:
        """Execute a step and return a structured step result."""
        # TODO: Define standardized execution lifecycle hooks.
        pass
