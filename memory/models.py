"""Shared data models for the ALARA memory layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SessionEntry(BaseModel):
    """Represents a single goal execution session."""
    
    id: str = Field(description="UUID4 identifier")
    session_id: str = Field(description="Groups entries by run")
    goal: str = Field(description="The original goal string")
    scope: str = Field(description="From GoalContext")
    status: str = Field(description="'success' | 'failed' | 'partial'")
    steps_total: int = Field(description="Total steps in the execution")
    steps_completed: int = Field(description="Number of steps completed")
    steps_failed: int = Field(description="Number of steps failed")
    execution_log: list[dict] = Field(description="Full log from OrchestratorResult")
    created_at: str = Field(description="UTC ISO timestamp")
    completed_at: str | None = Field(default=None, description="UTC ISO timestamp")


class PreferenceEntry(BaseModel):
    """Represents a user preference or inferred behavior."""
    
    id: str = Field(description="UUID4 identifier")
    key: str = Field(description="Unique preference key")
    value: str = Field(description="Stored as JSON string")
    category: str = Field(
        description="'path', 'tool', 'style', 'alias', 'package', 'general'"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="How certain we are (0.0 to 1.0)"
    )
    source: str = Field(
        default="user_explicit",
        description="'user_explicit' | 'inferred' | 'default'"
    )
    usage_count: int = Field(default=0, description="How many times this was used")
    last_used_at: str | None = Field(default=None, description="UTC ISO timestamp")
    created_at: str = Field(description="UTC ISO timestamp")
    updated_at: str = Field(description="UTC ISO timestamp")


class SkillEntry(BaseModel):
    """Represents a successful task pattern that can be reused."""
    
    id: str = Field(description="UUID4 identifier")
    name: str = Field(description="Human readable skill name")
    goal_pattern: str = Field(description="The goal that created this skill")
    scope: str = Field(description="From GoalContext")
    complexity: str = Field(description="From GoalContext")
    steps: list[dict] = Field(description="Serialized Step list")
    success_count: int = Field(default=0, description="Times this skill was used successfully")
    failure_count: int = Field(default=0, description="Times this skill failed")
    avg_duration_ms: float = Field(default=0.0, description="Average execution duration")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    created_at: str = Field(description="UTC ISO timestamp")
    last_used_at: str | None = Field(default=None, description="UTC ISO timestamp")
    updated_at: str = Field(description="UTC ISO timestamp")


class MemoryContext(BaseModel):
    """Context provided to the Planner to inform planning."""
    
    session_id: str
    recent_goals: list[SessionEntry] = Field(description="Last 10 session entries")
    relevant_skills: list[SkillEntry] = Field(description="Skills matching current goal")
    relevant_preferences: list[PreferenceEntry]
    known_paths: dict[str, str] = Field(description="Alias -> absolute path mapping")
    summary: str = Field(description="Formatted string for Gemini injection")


__all__ = [
    "SessionEntry",
    "PreferenceEntry", 
    "SkillEntry",
    "MemoryContext",
]
