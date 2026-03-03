"""Abstract base capability contract used by all execution capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityResult:
    """Normalized result contract returned by all capability executions."""

    success: bool
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls, output: str | None = None, metadata: dict[str, Any] | None = None
    ) -> CapabilityResult:
        return cls(success=True, output=output, metadata=metadata or {})

    @classmethod
    def fail(
        cls, error: str, metadata: dict[str, Any] | None = None
    ) -> CapabilityResult:
        return cls(success=False, error=error, metadata=metadata or {})


class BaseCapability(ABC):
    """Base class for all capabilities that execute operations."""

    @abstractmethod
    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        """Execute one operation with operation-specific params."""

    def supports(self, operation: str) -> bool:
        """Return whether this capability handles the operation."""
        return False
