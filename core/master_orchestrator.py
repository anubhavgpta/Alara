import json
from typing import List, Dict, Any, Optional
from loguru import logger

from alara.agents.registry import AgentRegistry
from alara.agents.base import BaseAgent, AgentResult
from alara.core.goal_understander import GoalUnderstander
from alara.core.chain import ChainContext
from alara.schemas.goal import GoalContext


class MasterOrchestrator:
    """
    Top-level coordinator for multi-agent execution.
    Receives goals, decomposes them if needed, assigns agents,
    and assembles results.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        config: dict,
        profile: dict
    ):
        self.registry = registry
        self.config = config
        self.profile = profile
        
        # Initialize goal understander for decomposition
        model = config.get("model", "gemini-2.5-flash")
        api_key = config.get("api_key", "")
        provider = config.get("provider", "gemini")
        
        self.understander = GoalUnderstander(
            model=model,
            api_key=api_key,
            provider=provider
        )
        self.chain = ChainContext()

    def run(
        self,
        goal: str,
        console=None
    ) -> List[AgentResult]:
        """
        Main entry point. Returns list of
        AgentResult (one per agent assignment).
        """
        # 1. Understand the goal
        goal_ctx = self.understander.understand(goal)

        # 2. Decompose if complex multi-agent goal
        assignments = self._decompose(
            goal, goal_ctx
        )

        # 3. Execute each assignment
        results = []
        previous_outputs = []  # Collect outputs from previous agents
        
        for i, assignment in enumerate(assignments):
            if len(assignments) > 1:
                console and console.print(
                    f"\n[dim]Assignment "
                    f"{i+1}/{len(assignments)}: "
                    f"{assignment['agent']} → "
                    f"{assignment['goal'][:60]}"
                    f"[/dim]"
                )

            # Inject previous outputs into sub-goal if available
            if previous_outputs:
                context = "\n\n".join(previous_outputs)
                enriched_goal = (
                    f"{assignment['goal']}\n\n"
                    f"Use the following content from "
                    f"previous steps:\n{context}"
                )
            else:
                enriched_goal = assignment['goal']

            agent = self.registry._get_or_init(
                assignment["agent"]
            )
            if not agent:
                agent = self.registry.select_agent(
                    assignment["goal"],
                    goal_ctx.scope
                )

            result = agent.run(
                goal=enriched_goal,
                chain_context=self.chain
                    if not self.chain.is_empty
                    else None
            )

            # Collect output for next agent
            if result.key_outputs:
                previous_outputs.extend(result.key_outputs)
            elif hasattr(result, 'output') and result.output:
                previous_outputs.append(result.output)

            self.chain.add(
                goal=assignment["goal"],
                task_graph=None,
                execution_log=result.execution_log,
                success=result.success
            )

            results.append(result)

        return results

    def _decompose(
        self,
        goal: str,
        goal_ctx: GoalContext
    ) -> List[Dict[str, str]]:
        """
        Decompose a goal into agent assignments.

        For simple goals (single scope, no
        conjunctions), return single assignment.

        For complex goals, use Gemini to decompose
        into ordered assignments.

        Returns list of:
          {"agent": agent_name, "goal": sub_goal}
        """

        # Simple heuristic first — if goal is
        # simple complexity and single scope,
        # skip LLM decomposition
        if goal_ctx.estimated_complexity == "simple":
            agent = self.registry.select_agent(
                goal, goal_ctx.scope
            )
            return [{"agent": agent.name,
                     "goal": goal}]

        # For moderate/complex, try LLM decomposition
        try:
            return self._llm_decompose(goal, goal_ctx)
        except Exception as e:
            logger.warning(
                f"Decomposition failed: {e}, "
                f"falling back to single agent"
            )
            agent = self.registry.select_agent(
                goal, goal_ctx.scope
            )
            return [{"agent": agent.name,
                     "goal": goal}]

    def _llm_decompose(
        self,
        goal: str,
        goal_ctx: GoalContext
    ) -> List[Dict[str, str]]:
        """
        Use Gemini to decompose a complex goal
        into agent assignments.
        """
        available_agents = \
            self.registry.list_registered()

        prompt = f"""
        You are the Master Orchestrator for ALARA,
        a personal AI agent system.

        Available agents:
        {chr(10).join(f'- {a}' for a in available_agents)}

        Agent capabilities:
        - coding: builds apps, writes/edits code,
          runs commands, installs packages
        - document: creates/edits Word docs,
          PowerPoint, PDF, Markdown, text files
        - research: web searches, summarizes info
        - writing: creative and professional writing
        - filesystem: file and folder operations
        - browser: web browser automation
        - comms: email, Slack, calendar via Composio

        User goal: {goal}
        Goal complexity: {goal_ctx.estimated_complexity}
        Goal scope: {goal_ctx.scope}

        Decompose this goal into ordered agent
        assignments. Each assignment is one focused
        sub-goal for one agent.

        Rules:
        - Only decompose if the goal genuinely
          requires multiple agents
        - If one agent can handle it entirely,
          return just one assignment
        - Assignments run in order — later agents
          can use outputs from earlier agents
        - Keep sub-goals specific and actionable
        - Maximum 4 assignments

        Respond with JSON only:
        {{
          "assignments": [
            {{
              "agent": "agent_name",
              "goal": "specific sub-goal for this agent"
            }}
          ]
        }}
        """

        # Call Gemini for decomposition
        from google import genai
        client = genai.Client(
            api_key=self.config.get("api_key")
        )
        response = client.models.generate_content(
            model=self.config.get(
                "model", "gemini-2.5-flash"
            ),
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                max_output_tokens=1024,
                temperature=0.1
            )
        )

        text = response.text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]

        data = json.loads(text)
        assignments = data.get("assignments", [])

        # Validate agent names
        registered = self.registry.list_registered()
        for a in assignments:
            if a["agent"] not in registered:
                # Find closest match
                a["agent"] = "filesystem"

        return assignments if assignments else [
            {"agent": self.registry.select_agent(
                goal, goal_ctx.scope
            ).name, "goal": goal}
        ]
