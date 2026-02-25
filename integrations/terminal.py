"""
alara/integrations/terminal.py

Controls Windows Terminal / PowerShell by voice.
Week 1-2: Stubs. Week 5-6: Real implementation.
"""
from loguru import logger


class TerminalIntegration:

    def run_command(self, params: dict):
        command = params.get("command", "")
        logger.info(f"[STUB] Running terminal command: {command}")
        # TODO Week 5:
        # Option A (new terminal window): subprocess.Popen(["wt", "powershell", "-Command", command])
        # Option B (inject into existing terminal): win32 SendKeys to active terminal window
        # Recommendation: start with Option A for reliability
