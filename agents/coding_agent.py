from alara.agents.base import BaseAgent


class CodingAgent(BaseAgent):
    name = "coding"
    description = "Builds, edits, and debugs code"
    capabilities = ["filesystem", "cli", "code"]

    system_prompt = """
    You are the Coding Agent for ALARA.
    You specialize in software development tasks.

    Your strengths:
    - Scaffolding new projects and applications
    - Writing clean, well-structured code
    - Debugging and fixing errors
    - Installing dependencies and setting up environments
    - Editing existing code files precisely

    When planning:
    - Always use absolute paths
    - Prefer create_file for writing code
    - Use run_command for pip install and CLI tools
    - Never start servers or run curl tests
    - Final step should verify the created files exist

    You have access to: filesystem, CLI, code analysis
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        coding_keywords = [
            "code", "script", "function", "class",
            "app", "api", "project", "debug", "fix",
            "install", "pip", "venv", "python",
            "javascript", "typescript", "fastapi",
            "flask", "django", "build", "develop"
        ]
        
        goal_lower = goal.lower()
        
        if scope in ("cli", "mixed"):
            return True
        
        return any(keyword in goal_lower for keyword in coding_keywords)
