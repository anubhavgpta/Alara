from alara.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    name = "research"
    description = "Researches topics using web search"
    capabilities = ["cli", "filesystem"]

    system_prompt = """
    You are the Research Agent for ALARA.
    You specialize in finding and synthesizing information.

    Your strengths:
    - Searching the web for current information
    - Summarizing and synthesizing multiple sources
    - Fact-checking and verifying claims
    - Compiling research into structured documents

    When planning:
    - Use run_command with curl or python -c for web
      requests where appropriate
    - Save research findings to files for other agents
    - Structure output clearly with sections

    You have access to: CLI for web requests, filesystem
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        research_keywords = [
            "research", "find", "search", "look up",
            "what is", "who is", "summarize", "compare",
            "analyze", "investigate", "gather info",
            "find information", "web search"
        ]
        
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in research_keywords)
