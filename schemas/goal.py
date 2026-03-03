"""Goal schema definitions for normalized user intent and constraints."""

from __future__ import annotations

from pydantic import BaseModel


class GoalContext(BaseModel):
    """Structured representation of a user's high-level goal."""

    # TODO: Add goal fields (raw goal, normalized intent, constraints, metadata).
    pass
