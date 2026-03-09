from alara.agents.base import BaseAgent


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
