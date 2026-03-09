from loguru import logger

class ComposioCapability:
    """
    Composio integration — coming soon.
    Stub returns informative error for all ops.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def execute(
        self, operation: str, params: dict
    ):
        from alara.capabilities.filesystem import (
            CapabilityResult
        )
        logger.info(
            f"CommsAgent: {operation} requested "
            f"— Composio integration coming soon"
        )
        return CapabilityResult(
            success=False,
            error=(
                "Comms agent is not yet available. "
                "Composio integration is coming "
                "in the next release."
            )
        )
