"""
alara/core/executor.py

Receives a structured Action and dispatches it to the correct integration module.
Each integration module is independent and exposes a single execute(params) method.

In Week 1-2, only stub modules are wired — they log what they would do.
Real implementations are added in Weeks 5-8.
"""

from loguru import logger
from alara.core.intent_engine import Action
from alara.integrations.windows_os import WindowsOSIntegration
from alara.integrations.terminal import TerminalIntegration
from alara.integrations.browser import BrowserIntegration
from alara.integrations.vscode import VSCodeIntegration


# ── Response ──────────────────────────────────────────────────────────────────

class ExecutionResult:
    def __init__(self, success: bool, message: str = ""):
        self.success = success
        self.message = message

    def __repr__(self):
        status = "✓" if self.success else "✗"
        return f"ExecutionResult({status} {self.message})"


# ── Executor ──────────────────────────────────────────────────────────────────

class Executor:
    """
    Routes Action objects to the appropriate integration module.

    Add new integrations by:
    1. Creating alara/integrations/your_module.py
    2. Registering its actions in _build_router() below
    """

    # Minimum confidence to attempt execution
    MIN_CONFIDENCE = 0.4

    def __init__(self):
        self.windows = WindowsOSIntegration()
        self.terminal = TerminalIntegration()
        self.browser = BrowserIntegration()
        self.vscode = VSCodeIntegration()
        self._router = self._build_router()

    def _build_router(self) -> dict:
        """Map action names to handler methods."""
        return {
            # Windows OS
            "open_app":          self.windows.open_app,
            "close_app":         self.windows.close_app,
            "switch_app":        self.windows.switch_app,
            "minimize_window":   self.windows.minimize_window,
            "maximize_window":   self.windows.maximize_window,
            "close_window":      self.windows.close_window,
            "take_screenshot":   self.windows.take_screenshot,
            "open_file":         self.windows.open_file,
            "open_folder":       self.windows.open_folder,
            "search_files":      self.windows.search_files,
            "volume_up":         self.windows.volume_up,
            "volume_down":       self.windows.volume_down,
            "volume_mute":       self.windows.volume_mute,
            "lock_screen":       self.windows.lock_screen,

            # Terminal
            "run_command":       self.terminal.run_command,

            # Browser
            "browser_new_tab":   self.browser.new_tab,
            "browser_navigate":  self.browser.navigate,
            "browser_search":    self.browser.search,
            "browser_close_tab": self.browser.close_tab,

            # VS Code
            "vscode_open_file":    self.vscode.open_file,
            "vscode_new_terminal": self.vscode.new_terminal,
            "vscode_search":       self.vscode.search,
        }

    def execute(self, action: Action) -> ExecutionResult:
        """
        Execute an action. Returns ExecutionResult indicating success/failure.
        """
        if action.action == "unknown":
            msg = f"Command not understood: '{action.raw_text}'"
            logger.warning(msg)
            return ExecutionResult(success=False, message=msg)

        if action.confidence < self.MIN_CONFIDENCE:
            msg = (
                f"Low confidence ({action.confidence:.2f}) for '{action.raw_text}' "
                f"— skipping execution"
            )
            logger.warning(msg)
            return ExecutionResult(success=False, message=msg)

        handler = self._router.get(action.action)
        if not handler:
            msg = f"No handler registered for action: '{action.action}'"
            logger.error(msg)
            return ExecutionResult(success=False, message=msg)

        try:
            logger.info(f"Executing: {action.action}({action.params})")
            handler(action.params)
            return ExecutionResult(success=True, message=f"Executed {action.action}")
        except Exception as e:
            msg = f"Execution error in {action.action}: {e}"
            logger.error(msg)
            return ExecutionResult(success=False, message=msg)
