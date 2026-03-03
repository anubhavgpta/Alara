"""Legacy compatibility wrapper for ALARA orchestration."""

from __future__ import annotations


class AlaraPipeline:
    """Backward-compatible pipeline facade around the new orchestrator."""

    def __init__(self) -> None:
        """Initialize pipeline dependencies."""
        # TODO: Remove this shim after migration to AlaraOrchestrator.
        pass

    def start(self) -> None:
        """Start method retained for compatibility with legacy entrypoints."""
        # TODO: Decide long-term behavior for legacy pipeline start.
        pass
