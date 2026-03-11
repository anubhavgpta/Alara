from __future__ import annotations
import json
from loguru import logger
from alara.agents.base import BaseAgent, AgentResult

class ResearchAgent(BaseAgent):

    name = "research"
    description = (
        "Researches topics by delegating web "
        "search and scraping to BrowserAgent, "
        "then summarizes findings with Gemini"
    )
    capabilities = ["browser", "filesystem"]

    system_prompt = """
You are the Research Agent for ALARA.
You gather information from the web and
synthesize it into clear, accurate summaries.

Your workflow:
1. Plan what to search or scrape
2. Delegate each web task to the browser
3. Collect and synthesize results
4. Return a well-structured prose summary

Always cite sources. Keep summaries concise
but complete. Use plain prose, not bullets.
"""

    def can_handle(
        self, goal: str, scope: str
    ) -> bool:
        keywords = [
            "research", "find", "search",
            "look up", "what is", "who is",
            "how does", "explain", "summarize",
            "latest", "recent", "news",
            "information about", "tell me about",
            "investigate", "compare", "analyze",
            "overview", "details about",
            "what are", "how to",
        ]
        goal_lower = goal.lower()
        return any(
            k in goal_lower for k in keywords
        )

    def _plan_tasks(
        self, goal: str
    ) -> list[dict]:
        """
        Ask Gemini to plan 2-4 browser tasks
        needed to research the goal.
        """
        self._ensure_initialized()

        from google import genai
        from google.genai import types

        prompt = f"""
You are a research planner. Given a research
goal, output a JSON list of web tasks.

Each task must have:
- "type": "search_web" or "scrape"
- "query": search terms (for search_web only)
- "url": full URL (for scrape only)
- "purpose": one sentence why this helps

Rules:
- Use search_web for broad topic research
- Use scrape only when a specific URL is given
- 2 tasks minimum, 4 tasks maximum
- Prefer search_web over scrape

Research goal: {goal}

Respond with ONLY a valid JSON array.
No markdown, no explanation, no extra text.
"""

        try:
            client = genai.Client(
                api_key=self.config.get(
                    "api_key", ""
                )
            )
            response = client.models\
                .generate_content(
                    model=self.config.get(
                        "model",
                        "gemini-2.5-flash"
                    ),
                    contents=prompt,
                    config=types\
                        .GenerateContentConfig(
                            max_output_tokens=500,
                            temperature=0.1
                        )
                )

            text = response.text.strip()
            if "```" in text:
                text = text.split(
                    "```"
                )[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            tasks = json.loads(text)
            logger.info(
                f"[research] Planned "
                f"{len(tasks)} tasks: "
                f"{[t.get('type') for t in tasks]}"
            )
            return tasks[:4]

        except Exception as e:
            logger.warning(
                f"[research] Planning failed "
                f"({e}), using fallback"
            )
            return [{
                "type": "search_web",
                "query": goal,
                "purpose": "direct search"
            }]

    def _execute_browser_task(
        self,
        task: dict
    ) -> str:
        """
        Execute a browser task by calling
        BrowserCapability directly — bypasses
        the full agent planning pipeline to
        avoid unwanted file-saving side effects
        and to get the raw capability output.
        """
        from alara.capabilities.browser import (
            BrowserCapability
        )

        cap = BrowserCapability(self.config)
        task_type = task.get("type")

        try:
            if task_type == "search_web":
                query = task.get("query", "")
                logger.info(
                    f"[research] → search: {query}"
                )
                result = cap.execute(
                    "search_web",
                    {"query": query}
                )

            elif task_type == "scrape":
                url = task.get("url", "")
                logger.info(
                    f"[research] → scrape: {url}"
                )
                result = cap.execute(
                    "scrape",
                    {"url": url}
                )

            else:
                logger.warning(
                    f"[research] Unknown task "
                    f"type: {task_type}"
                )
                return ""

            if result.success and result.output:
                logger.info(
                    f"[research] Collected "
                    f"{len(result.output)} chars"
                )
                return result.output
            else:
                logger.warning(
                    f"[research] Task failed: "
                    f"{result.error}"
                )
                return ""

        except Exception as e:
            logger.error(
                f"[research] Task error: {e}"
            )
            return ""

    def _summarize(
        self,
        goal: str,
        content_blocks: list[str],
        tasks: list[dict]
    ) -> str:
        """
        Summarize all collected content
        into a clean prose answer.
        """
        from google import genai
        from google.genai import types

        # Filter empty blocks
        valid = [
            c for c in content_blocks if c
        ]

        if not valid:
            return (
                "Could not retrieve enough "
                "information to answer: "
                f"{goal}"
            )

        combined = "\n\n---\n\n".join(valid)

        # Trim to 10000 chars for context window
        if len(combined) > 10000:
            combined = combined[:10000] + "..."

        prompt = f"""
Research goal: {goal}

Raw content collected from the web:
{combined}

Write a clear, accurate summary that directly
answers the research goal. Use plain prose.
Mention key facts, figures, and dates.
Note the sources where relevant.
Be concise but complete.
"""

        try:
            client = genai.Client(
                api_key=self.config.get(
                    "api_key", ""
                )
            )
            response = client.models\
                .generate_content(
                    model=self.config.get(
                        "model",
                        "gemini-2.5-flash"
                    ),
                    contents=prompt,
                    config=types\
                        .GenerateContentConfig(
                            max_output_tokens=2000,
                            temperature=0.3
                        )
                )
            return response.text.strip()

        except Exception as e:
            logger.error(
                f"[research] Summarization "
                f"failed: {e}"
            )
            return combined[:2000]

    def run(
        self,
        goal: str,
        chain_context=None,
        memory_context=None
    ) -> AgentResult:

        self._ensure_initialized()

        logger.info(
            f"[research] Starting: {goal[:80]}"
        )

        try:
            # Plan tasks
            tasks = self._plan_tasks(goal)

            # Execute each task directly
            content_blocks = []
            for task in tasks:
                content = self._execute_browser_task(task)
                content_blocks.append(content)

            # Summarize
            logger.info(
                "[research] Summarizing..."
            )
            summary = self._summarize(
                goal, content_blocks, tasks
            )

            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=True,
                steps_completed=len(tasks),
                steps_total=len(tasks),
                key_outputs=[summary],
                execution_log=[],
                error=None
            )

        except Exception as e:
            logger.error(
                f"[research] Failed: {e}"
            )
            return AgentResult(
                agent_name=self.name,
                goal=goal,
                success=False,
                steps_completed=0,
                steps_total=1,
                key_outputs=[],
                execution_log=[],
                error=str(e)
            )
