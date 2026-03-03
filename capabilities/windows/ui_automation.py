"""Windows UI automation capability using pywinauto as a fallback layer."""

from __future__ import annotations

from typing import Any

from alara.capabilities.base import BaseCapability, CapabilityResult


class WindowsUIAutomationCapability(BaseCapability):
    """Execute UI automation steps when higher-level capabilities are unavailable."""

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        return CapabilityResult.fail(
            f"Windows UI automation not implemented for operation: {operation}"
        )
