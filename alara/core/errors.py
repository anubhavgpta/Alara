"""Custom exception hierarchy for Alara."""


class AlaraError(Exception):
    """Base class for all Alara-domain exceptions."""


class AlaraAPIError(AlaraError):
    """Raised when an external API call (Gemini, etc.) fails after all retries."""


class AlaraPermissionError(AlaraError):
    """Raised when a sandbox check or user permission gate rejects an action."""


class AlaraMCPError(AlaraError):
    """Raised when a Composio/MCP connection or tool call fails."""


class AlaraConfigError(AlaraError):
    """Raised when required configuration or secrets are missing or invalid."""
