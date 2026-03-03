"""Task graph schema definitions for planner and orchestrator coordination."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class StepType(str, Enum):
    """Supported execution step categories."""

    # TODO: Add concrete step type values.
    pass


class Step(BaseModel):
    """Single executable step in a task graph."""

    # TODO: Add step fields (id, type, description, payload).
    pass


class StepResult(BaseModel):
    """Execution result for one step."""

    # TODO: Add step result fields (success, output, error, metadata).
    pass


class TaskGraph(BaseModel):
    """Planner-produced graph of steps for orchestrator execution."""

    # TODO: Add task graph fields (goal id, step list, dependencies).
    pass
