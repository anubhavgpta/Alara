"""Legacy assistant module retained during migration to orchestrator architecture."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionStats:
    """Placeholder session statistics container for legacy compatibility."""

    total_commands: int = 0
    successful_commands: int = 0
    reprompts: int = 0


class AlaraAssistant:
    """Legacy assistant facade during v0.2 architecture transition."""

    def __init__(self, user_id: str = "default") -> None:
        """Initialize legacy assistant placeholder."""
        # TODO: Migrate callers to AlaraOrchestrator and remove this class.
        pass

    def run(self) -> None:
        """Run method retained for compatibility with older scripts."""
        # TODO: Implement or remove legacy assistant runtime path.
        pass
