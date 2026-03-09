from alara.agents.base import BaseAgent
from alara.agents.base import AgentResult
from alara.core.chain import ChainContext

class CommsAgent(BaseAgent):
    """
    Comms Agent — coming soon.
    Will support Gmail, Slack, Calendar,
    Notion and more via Composio.
    """

    name = "comms"
    description = (
        "Sends emails, messages, calendar events "
        "— coming soon"
    )
    capabilities = []
    system_prompt = ""

    def can_handle(
        self, goal: str, scope: str
    ) -> bool:
        keywords = [
            "email", "gmail", "send message",
            "slack", "whatsapp", "notify",
            "calendar", "schedule", "meeting",
            "invite", "notion", "task",
            "composio", "webhook", "message me",
            "remind me", "set a reminder",
            "discord", "linear", "trello",
            "send a notification", "dm me",
        ]
        goal_lower = goal.lower()
        return any(
            k in goal_lower for k in keywords
        )

    def run(
        self,
        goal: str,
        chain_context: ChainContext | None = None,
        memory_context=None
    ) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            goal=goal,
            success=False,
            steps_completed=0,
            steps_total=0,
            key_outputs=[],
            execution_log=[],
            error=(
                "Comms agent is not yet available. "
                "Composio integration is coming "
                "in the next release."
            )
        )
