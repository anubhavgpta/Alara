"""Execution routing module for dispatching steps across capability layers."""

from __future__ import annotations

from loguru import logger

from alara.capabilities.base import BaseCapability, CapabilityResult
from alara.capabilities.cli import CLICapability
from alara.capabilities.code import CodeCapability
from alara.capabilities.filesystem import FilesystemCapability
from alara.capabilities.system import SystemCapability
from alara.capabilities.document import DocumentCapability
from alara.schemas.task_graph import Step, StepType


class ExecutionRouter:
    """Route plan steps to the best available capability implementation."""

    def __init__(self, config=None) -> None:
        self.config = config or {}
        self.filesystem = FilesystemCapability()
        self.cli = CLICapability()
        self.system = SystemCapability()
        self.code = CodeCapability()
        self.document = DocumentCapability()
        
        # Document operations set
        self.DOCUMENT_OPS = {
            "create_word_doc", "edit_word_doc",
            "read_word_doc", "create_powerpoint",
            "edit_powerpoint", "read_powerpoint",
            "create_pdf", "read_pdf",
            "create_markdown", "edit_markdown",
            "read_text", "edit_text"
        }
        
        # Browser operations set
        self.BROWSER_OPS = {
            "navigate", "click", "type", "scrape",
            "screenshot", "fill_form", "submit_form",
            "get_links", "wait_for", "extract_table",
            "search_web"
        }
        
        # Composio operations set
        self.COMPOSIO_OPS = {
            "send_email", "read_emails",
            "create_calendar_event",
            "get_calendar_events",
            "send_slack_message",
            "create_notion_page",
            "update_notion_page",
            "create_task",
            "send_whatsapp",
            "trigger_webhook"
        }

    def route(self, step: Step) -> CapabilityResult:
        """Execute a single step using the capability hierarchy."""
        logger.debug("Routing step {} ({}) to capability", step.id, step.operation)
        
        try:
            # Route document operations directly to DocumentCapability
            if step.operation in self.DOCUMENT_OPS or step.step_type == StepType.DOCUMENT:
                return self.document.execute(step.operation, step.params)
            
            # Route browser operations directly to BrowserCapability
            if step.operation in self.BROWSER_OPS or step.step_type == StepType.BROWSER:
                from alara.capabilities.browser import BrowserCapability
                return BrowserCapability(self.config).execute(step.operation, step.params)
            
            # Route Composio operations directly to ComposioCapability
            if step.operation in self.COMPOSIO_OPS or step.step_type == StepType.APP_ADAPTER or step.step_type == StepType.COMMS:
                from alara.capabilities.composio_capability import ComposioCapability
                return ComposioCapability(self.config).execute(step.operation, step.params)
            
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

            elif step.step_type == StepType.DOCUMENT:
                return self.document.execute(step.operation, step.params)

            elif step.step_type == StepType.BROWSER:
                from alara.capabilities.browser import BrowserCapability
                return BrowserCapability(self.config).execute(step.operation, step.params)

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
