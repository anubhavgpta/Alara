from dataclasses import dataclass, field
from typing import Optional, Union
from alara.core.planner import Planner
from alara.core.orchestrator import Orchestrator
from alara.core.goal_understander import GoalUnderstander
from alara.core.chain import ChainContext
from alara.memory import MemoryManager
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import TaskGraph
from loguru import logger


@dataclass
class AgentResult:
    agent_name: str
    goal: str
    success: bool
    steps_completed: int
    steps_total: int
    key_outputs: list[str]
    execution_log: list
    error: Optional[str] = None


class BaseAgent:
    """
    Base class for all Alara agents.
    Each agent wraps a full plan → execute loop
    with agent-specific system prompt and
    capability set.
    """

    # Subclasses must define these
    name: str = "base"
    description: str = ""
    capabilities: list[str] = []  # capability names
    system_prompt: str = ""

    def __init__(self, config: dict, profile: dict):
        self.config = config
        self.profile = profile
        self.memory = MemoryManager.get_instance()
        self._setup_pipeline()

    def _setup_pipeline(self):
        """Initialize planner and orchestrator
        with agent-specific system prompt."""
        model = self.config.get(
            "model", "gemini-2.5-flash"
        )
        api_key = self.config.get("api_key", "")
        provider = self.config.get(
            "provider", "gemini"
        )

        self.understander = GoalUnderstander(
            model=model,
            api_key=api_key,
            provider=provider
        )
        self.planner = Planner(
            model=model,
            api_key=api_key,
            provider=provider,
            agent_system_prompt=self.system_prompt
        )
        self.orchestrator = Orchestrator(
            allowed_capabilities=self.capabilities
        )

    def can_handle(self, goal: str,
                   scope: str) -> bool:
        """
        Return True if this agent can handle
        the given goal. Subclasses override this.
        """
        return False

    def run(
        self,
        goal: str,
        chain_context: Optional[ChainContext] = None,
        memory_context=None
    ) -> AgentResult:
        """
        Full plan → execute loop for one goal.
        Returns AgentResult.
        """
        logger.info(
            f"[{self.name}] Starting: {goal[:60]}"
        )
        try:
            # Understand
            goal_ctx = self.understander.understand(
                goal
            )

            # Build memory context
            if memory_context is None:
                memory_context = \
                    self.memory.build_context(
                        goal, goal_ctx
                    )

            # Plan
            chain_context_block = None
            if chain_context and not chain_context.is_empty:
                chain_context_block = chain_context.build_context_block()
            
            task_graph = self.planner.plan(
                goal_context=goal_ctx,
                memory_context=memory_context,
                chain_context=chain_context_block
            )

            # Execute
            result = self.orchestrator.run(
                task_graph
            )

            # Update memory
            # Note: MemoryManager.after_execution expects OrchestratorResult
            # but agents work with AgentResult. For now, skip memory update
            # at agent level - it's handled at master orchestrator level
            # self.memory.after_execution(
            #     goal=goal,
            #     goal_context=goal_ctx,
            #     task_graph=task_graph,
            #     execution_log=\
            #         self.orchestrator\
            #             .last_execution_log,
            #     success=result.success
            # )

            # Extract key outputs
            key_outputs = self._extract_outputs(
                self.orchestrator.last_execution_log
            )

            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=result.success,
                steps_completed=result.steps_completed,
                steps_total=result.total_steps,
                key_outputs=key_outputs,
                execution_log=\
                    self.orchestrator\
                        .last_execution_log
            )

        except Exception as e:
            logger.error(
                f"[{self.name}] Failed: {e}"
            )
            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=False,
                steps_completed=0,
                steps_total=0,
                key_outputs=[],
                execution_log=[],
                error=str(e)
            )

    def _extract_outputs(
        self, execution_log: list
    ) -> list[str]:
        """Extract key outputs from execution log."""
        outputs = []
        for entry in execution_log:
            if not entry.get("success"):
                continue
            vd = entry.get(
                "verification_detail", ""
            )
            if vd and vd.startswith("Path exists:"):
                outputs.append(
                    vd.replace("Path exists:", "")
                         .strip()
                )
            out = entry.get("output", "")
            if out and out != "(no output)" \
                    and len(out) < 200:
                outputs.append(out)
        return outputs
