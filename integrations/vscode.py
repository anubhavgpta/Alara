"""
alara/integrations/vscode.py

Controls VS Code via the CLI and keyboard shortcuts.
Week 1-2: Stubs. Week 7-8: Real implementation.
"""
from loguru import logger


class VSCodeIntegration:

    def open_file(self, params: dict):
        query = params.get("query", "")
        logger.info(f"[STUB] VS Code: opening file matching '{query}'")
        # TODO Week 7:
        # subprocess.Popen(["code", "--goto", resolved_path])
        # Or: send Ctrl+P to VS Code window then type the query

    def new_terminal(self, params: dict):
        logger.info("[STUB] VS Code: opening new terminal panel")
        # TODO Week 7: send Ctrl+` to VS Code window

    def search(self, params: dict):
        query = params.get("query", "")
        logger.info(f"[STUB] VS Code: searching for '{query}'")
        # TODO Week 7: send Ctrl+Shift+F to VS Code, then type query
