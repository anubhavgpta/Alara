from alara.agents.base import BaseAgent


class BrowserAgent(BaseAgent):
    name = "browser"
    description = "Controls web browser via Playwright"
    capabilities = ["cli"]

    system_prompt = """
    You are the Browser Agent for ALARA.
    You specialize in web browser automation.
    [Playwright integration coming soon]
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        browser_keywords = [
            "browser", "website", "webpage", "navigate",
            "click", "scroll", "scrape", "selenium",
            "playwright", "open chrome", "open tab"
        ]
        
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in browser_keywords)

    def run(self, goal: str, chain_context=None, memory_context=None):
        """Override run to return stub response."""
        from alara.agents.base import AgentResult
        
        return AgentResult(
            agent_name=self.name,
            goal=goal,
            success=False,
            steps_completed=0,
            steps_total=0,
            key_outputs=[],
            execution_log=[],
            error="Browser Agent requires Playwright — coming in next release."
        )
