"""Data models for background task tracking."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    id: int
    description: str
    status: TaskStatus
    result: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
