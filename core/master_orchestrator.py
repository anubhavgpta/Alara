import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from typing import List, Dict, Any, Optional
from loguru import logger

from agents.registry import AgentRegistry
from agents.base import BaseAgent, AgentResult
from core.goal_understander import GoalUnderstander
from core.chain import ChainContext
from schemas.goal import GoalContext


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

        # 3. Execute assignments in waves (parallel within each wave)
        results = []
        collected_outputs = []
        
        # Group tasks by priority (wave)
        sorted_tasks = sorted(
            assignments,
            key=lambda x: x.get('priority', 1)
        )
        waves = {
            k: list(v)
            for k, v in groupby(
                sorted_tasks,
                key=lambda x: x.get('priority', 1)
            )
        }

        for wave_num in sorted(waves.keys()):
            wave_tasks = waves[wave_num]
            wave_label = (
                f"Wave {wave_num}: "
                f"{[t['agent'] for t in wave_tasks]}"
            )
            logger.info(
                f"[orchestrator] Running {wave_label}"
            )

            # Print terminal output for this wave
            if len(wave_tasks) > 1:
                console and console.print(
                    f"\n[bold][Parallel] Running {len(wave_tasks)} agents simultaneously:[/bold]"
                )
                agent_list = ", ".join([f"→ {t['agent']}" for t in wave_tasks])
                console and console.print(f"  {agent_list}")
            else:
                console and console.print(
                    f"\n[dim]Assignment {wave_num}/{len(waves)}: "
                    f"{wave_tasks[0]['agent']} → "
                    f"{wave_tasks[0]['goal'][:60]}[/dim]"
                )

            # Execute wave in parallel
            wave_results = self._run_wave(
                wave_tasks, collected_outputs, goal_ctx
            )

            # Collect outputs for next wave
            for result in wave_results:
                if result.success and result.key_outputs:
                    collected_outputs.extend(result.key_outputs)
                elif hasattr(result, 'output') and result.output:
                    collected_outputs.append(result.output)

                # Add to chain context
                task = next(t for t in wave_tasks if t['agent'] == result.agent_name if hasattr(result, 'agent_name'))
                if not task:
                    task = wave_tasks[0] if len(wave_tasks) == 1 else wave_tasks[0]
                
                self.chain.add(
                    goal=task["goal"],
                    task_graph=None,
                    execution_log=result.execution_log,
                    success=result.success
                )

            results.extend(wave_results)

        return results

    def _decompose(
        self,
        goal: str,
        goal_ctx: GoalContext
    ) -> List[Dict[str, Any]]:
        """
        Decompose a goal into agent assignments.

        For simple goals (single scope, no
        conjunctions), return single assignment.

        For complex goals, use Gemini to decompose
        into ordered assignments.

        Returns list of:
          {"agent": agent_name, "goal": sub_goal, "priority": int}
        """

        # Simple heuristic first — if goal is
        # simple complexity and single scope,
        # skip LLM decomposition
        if goal_ctx.estimated_complexity == "simple":
            agent = self.registry.select_agent(
                goal, goal_ctx.scope
            )
            return [{"agent": agent.name,
                     "goal": goal, "priority": 1}]

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
                     "goal": goal, "priority": 1}]

    def _llm_decompose(
        self,
        goal: str,
        goal_ctx: GoalContext
    ) -> List[Dict[str, Any]]:
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

        Assign priority carefully:
          priority 1 = can start immediately, no deps
          priority 2 = depends on priority 1 output
          priority 3 = depends on priority 2 output

        Independent tasks at the same priority level
        will run in PARALLEL. Only assign higher
        priority to tasks that genuinely need prior
        output.

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
              "goal": "specific sub-goal for this agent",
              "priority": 1
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

        # Validate agent names and ensure priority
        registered = self.registry.list_registered()
        for a in assignments:
            if a["agent"] not in registered:
                # Find closest match
                a["agent"] = "filesystem"
            # Ensure priority field exists
            if "priority" not in a:
                a["priority"] = 1

        return assignments if assignments else [
            {"agent": self.registry.select_agent(
                goal, goal_ctx.scope
            ).name, "goal": goal, "priority": 1}
        ]

    def _run_wave(
        self,
        tasks: List[Dict[str, Any]],
        prior_outputs: List[str],
        goal_ctx: GoalContext = None
    ) -> List[AgentResult]:
        """
        Run all tasks in this wave in parallel
        using threads (agents are sync).
        Inject prior_outputs into each task's
        sub_goal.
        """
        def run_single(task):
            sub_goal = task['goal']
            agent_name = task['agent']

            # Extract injected content BEFORE it reaches agent.run()
            injected_content = None
            CONTENT_MARKER = "Output from prior step:\n"
            if CONTENT_MARKER in sub_goal:
                # Extract the raw content block
                marker_idx = sub_goal.find(CONTENT_MARKER)
                if marker_idx != -1:
                    # Get everything after the marker
                    injected_content = sub_goal[
                        marker_idx + len(CONTENT_MARKER):
                    ].strip()
                    # Remove the injected content from sub_goal to prevent
                    # Planner from seeing/rewriting it
                    sub_goal = sub_goal[:marker_idx].strip()

            # Inject prior outputs as context (only if no extracted content)
            if prior_outputs and not injected_content:
                context = "\n\n".join(
                    f"Output from prior step:\n{o}"
                    for o in prior_outputs
                )
                sub_goal = (
                    f"{sub_goal}\n\n"
                    f"Use this content:\n{context}"
                )

            agent = self.registry._get_or_init(
                agent_name
            )
            if not agent:
                # Fallback to select_agent
                agent = self.registry.select_agent(
                    sub_goal, None
                )
            
            # Pass working_directory to coding agent if available
            if hasattr(agent, 'rica') and goal_ctx and goal_ctx.working_directory:
                agent._project_dir = goal_ctx.working_directory
                logger.info(
                    f"[orchestrator] Set project_dir for {agent_name}: {goal_ctx.working_directory}"
                )
            
            return agent.run(
                goal=sub_goal,
                injected_content=injected_content
            )

        with ThreadPoolExecutor(
            max_workers=len(tasks)
        ) as executor:
            futures = [
                executor.submit(run_single, task)
                for task in tasks
            ]
            results = [f.result() for f in futures]

        return results
