from agents.base import BaseAgent, AgentResult
from rica import RicaAgent
from rica.result import RicaResult
import uuid
from loguru import logger

class CodingAgent(BaseAgent):
    """
    Coding specialist agent.
    Delegates all coding tasks to Rica
    (Runtime Intelligent Coder Assistant).
    """

    name = "coding"
    description = "Builds, edits, and debugs code via Rica"
    capabilities = ["filesystem", "cli", "code"]

    def _initialize(self) -> None:
        self.rica = RicaAgent({
            "api_key": self.config.get(
                "api_key", ""
            ),
            "model": self.config.get(
                "model", "gemini-2.5-flash"
            ),
        })
        logger.info(
            "[coding] RicaAgent initialized"
        )

    def can_handle(self, goal: str, scope: str) -> bool:
        coding_keywords = [
            "code", "script", "function", "class",
            "app", "api", "project", "debug", "fix",
            "install", "pip", "venv", "python",
            "javascript", "typescript", "fastapi",
            "flask", "django", "build", "develop",
            "implement", "create", "write", "program",
            "add", "modify", "update", "append", "edit",
            "file", "path", "directory", "folder"
        ]
        
        goal_lower = goal.lower()
        
        if scope in ("app", "mixed", "cli"):
            return True
        
        return any(keyword in goal_lower for keyword in coding_keywords)

    def run(
        self,
        goal: str,
        chain_context=None,
        memory_context=None,
        injected_content: str | None = None,
    ) -> AgentResult:
        # Initialize Rica if not already done
        if not hasattr(self, 'rica'):
            self._initialize()
        
        # Build workspace name from goal
        ws_name = "alara_" + (
            goal[:20]
            .lower()
            .replace(" ", "_")
            .replace("/", "_")
            .strip("_")
        )
        
        # Resolve project_dir intelligently for existing files
        import os
        from pathlib import Path
        import re
        
        project_dir = None
        
        # Try to extract path from goal for existing files
        path_match = re.search(
            r'[A-Za-z0-9_.\\/-]+\.[a-z]{2,4}',
            goal
        )
        if path_match:
            candidate = Path(path_match.group())
            if not candidate.is_absolute():
                # Relative path — resolve against ALARA project root
                alara_root = Path(__file__).parent.parent
                resolved = alara_root / candidate
                if resolved.exists():
                    project_dir = str(alara_root)
                    logger.info(
                        f"[coding] Resolved project_dir"
                        f" from path in goal: {project_dir}"
                    )
        
        logger.info(
            f"[coding] Delegating to Rica: "
            f"{goal[:60]}"
        )
        
        # Pass project_dir to Rica if resolved
        rica_params = {
            "goal": goal,
            "workspace_name": ws_name,
        }
        if project_dir:
            rica_params["project_dir"] = project_dir
            logger.info(
                f"[coding] Project directory: {project_dir}"
            )

        result: RicaResult = self.rica.run(**rica_params)

        if result.success:
            summary = (
                f"Rica completed: "
                f"{len(result.files_created)} "
                f"file(s) created, "
                f"{result.iterations} "
                f"iteration(s)\n"
                f"Workspace: "
                f"{result.workspace_dir}\n"
                f"Files: "
                f"{', '.join(result.files_created)}"
            )
            logger.info(
                f"[coding] Rica succeeded: "
                f"{summary}"
            )
            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=True,
                key_outputs=[
                    result.summary,
                    *result.files_created,
                ],
                steps_completed=result.iterations,
                steps_total=result.iterations,
                steps_failed=0,
                execution_log=[{
                    "step_id": 1,
                    "operation": "rica_run",
                    "description": goal,
                    "attempt": 1,
                    "success": True,
                    "error": None,
                    "verified": True,
                    "workspace": result.workspace_dir,
                }],
            )
        else:
            logger.error(
                f"[coding] Rica failed: "
                f"{result.error}"
            )
            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=False,
                key_outputs=[],
                steps_completed=result.iterations,
                steps_total=result.iterations,
                steps_failed=1,
                execution_log=[{
                    "step_id": 1,
                    "operation": "rica_run",
                    "description": goal,
                    "attempt": 1,
                    "success": False,
                    "error": result.error,
                    "verified": False,
                    "workspace": result.workspace_dir,
                }],
            )
