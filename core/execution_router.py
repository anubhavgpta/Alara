"""Execution routing module for dispatching steps across capability layers."""

from __future__ import annotations

from loguru import logger

from alara.capabilities.base import BaseCapability, CapabilityResult
from alara.capabilities.cli import CLICapability
from alara.capabilities.code import CodeCapability
from alara.capabilities.filesystem import FilesystemCapability
from alara.capabilities.system import SystemCapability
from alara.schemas.task_graph import Step, StepType


class ExecutionRouter:
    """Route plan steps to the best available capability implementation."""

    def __init__(self) -> None:
        self.filesystem = FilesystemCapability()
        self.cli = CLICapability()
        self.system = SystemCapability()
        self.code = CodeCapability()

    def route(self, step: Step) -> CapabilityResult:
        """Execute a single step using the capability hierarchy."""
        logger.debug("Routing step {} ({}) to capability", step.id, step.operation)
        
        try:
            # Route code operations directly to CodeCapability
            if step.step_type == StepType.CODE or self.code.supports(step.operation):
                return self.code.execute(step.operation, step.params)
            
            # Route based on step_type with exact priority order
            if step.step_type == StepType.FILESYSTEM:
                if self.filesystem.supports(step.operation):
                    return self.filesystem.execute(step.operation, step.params)
                else:
                    logger.warning(
                        "Filesystem capability does not support operation '{}', falling back to CLI",
                        step.operation
                    )
                    return self.cli.execute(step.operation, step.params)

            elif step.step_type == StepType.CLI:
                return self.cli.execute(step.operation, step.params)

            elif step.step_type == StepType.SYSTEM:
                return self.system.execute(step.operation, step.params)

            elif step.step_type == StepType.APP_ADAPTER:
                logger.warning(
                    "App adapter not yet implemented, falling back to CLI for operation '{}'",
                    step.operation
                )
                return self.cli.execute(step.operation, step.params)

            elif step.step_type == StepType.VISION:
                logger.warning("Vision not yet implemented")
                return CapabilityResult.fail(
                    "Vision capability not available in this version"
                )

            else:
                logger.error("Unknown step type: {}", step.step_type)
                return CapabilityResult.fail(f"Unknown step type: {step.step_type}")

        except Exception as exc:
            logger.error("Routing exception for step {}: {}", step.id, exc)
            return CapabilityResult.fail(error=str(exc))
