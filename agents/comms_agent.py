from alara.agents.base import BaseAgent


class CommsAgent(BaseAgent):
    name = "comms"
    description = "Sends emails, messages via Zapier"
    capabilities = []

    system_prompt = """
    You are the Comms Agent for ALARA.
    You specialize in communication and messaging.
    [Zapier integration coming soon]
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        comms_keywords = [
            "email", "gmail", "send message", "slack",
            "whatsapp", "notify", "calendar", "schedule",
            "notion", "zapier", "webhook"
        ]
        
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in comms_keywords)

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
            error="Comms Agent requires Zapier integration — coming in next release."
        )
