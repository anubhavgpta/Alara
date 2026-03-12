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

        logger.info(
            f"[coding] Delegating to Rica: "
            f"{goal[:60]}"
        )

        result: RicaResult = self.rica.run(
            goal,
            workspace_name=ws_name,
        )

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
                    "output": summary,
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
                    "output": "",
                    "error": result.error,
                    "verified": False,
                    "workspace": result.workspace_dir,
                }],
            )
