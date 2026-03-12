from loguru import logger
from agents.base import BaseAgent

class FilesystemAgent(BaseAgent):
    name = "filesystem"
    description = "Manages files and directories"
    capabilities = ["filesystem", "system"]

    system_prompt = """
    You are the Filesystem Agent for ALARA.
    You specialize in file and directory operations.

    Your strengths:
    - Creating, moving, copying, and deleting files
    - Organizing directory structures
    - Searching for files by name or content
    - Managing system paths and environment

    When planning:
    - Always use absolute paths
    - Use create_directory before create_file
      when the parent directory may not exist
    - Verify existence after every create operation

    You have access to: filesystem, system operations
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        filesystem_keywords = [
            "file", "folder", "directory", "move",
            "copy", "delete", "rename", "create",
            "organize", "path", "backup"
        ]
        
        goal_lower = goal.lower()
        
        if scope == "filesystem":
            return True
        
        return any(keyword in goal_lower for keyword in filesystem_keywords)

    def run(self, goal: str, chain_context=None, memory_context=None, injected_content: str | None = None):
        """
        Override run to handle injected content directly.
        If injected_content is provided, use it as the result.
        """
        self._ensure_initialized()
        logger.info(
            f"[filesystem] Starting: {goal[:60]}"
        )
        
        # If injected content is provided, return it directly
        if injected_content is not None:
            logger.info(f"[filesystem] Using injected content directly ({len(injected_content)} chars)")
            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=True,
                steps_completed=1,
                steps_total=1,
                steps_failed=0,
                key_outputs=[injected_content],
                execution_log=[],
                error=None
            )
        
        # Otherwise, call parent run method
        return super().run(goal, chain_context, memory_context)
