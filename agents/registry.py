from typing import Optional
from alara.agents.coding_agent import CodingAgent
from alara.agents.document_agent import DocumentAgent
from alara.agents.research_agent import ResearchAgent
from alara.agents.writing_agent import WritingAgent
from alara.agents.filesystem_agent import FilesystemAgent
from alara.agents.browser_agent import BrowserAgent
from alara.agents.comms_agent import CommsAgent
from loguru import logger

# Map use_case → agent names to activate
USE_CASE_AGENTS = {
    "coding_development": [
        "coding", "filesystem", "document"
    ],
    "research_writing": [
        "research", "writing", "document",
        "filesystem"
    ],
    "creative_writing": [
        "writing", "document", "filesystem"
    ],
    "personal_productivity": [
        "filesystem", "document", "writing"
    ],
    "email_communications": [
        "comms", "writing", "document"
    ],
}

# All agents always available regardless of
# use case (core agents)
CORE_AGENTS = ["filesystem"]


class AgentRegistry:
    """
    Manages agent instantiation and selection.
    Agents are instantiated once and reused.
    """

    def __init__(
        self, config: dict, profile: dict
    ):
        self.config = config
        self.profile = profile
        self._agents: dict[str, "BaseAgent"] = {}
        self._load_agents()

    def _load_agents(self):
        """
        Instantiate agents based on user's
        declared use cases from profile.
        Always loads CORE_AGENTS.
        """
        use_cases = self.profile.get(
            "use_cases", []
        )

        active_names = set(CORE_AGENTS)
        for uc in use_cases:
            for name in USE_CASE_AGENTS.get(
                uc, []
            ):
                active_names.add(name)

        # If no use cases or "all", load everything
        if not use_cases or "all" in use_cases:
            active_names = {
                "coding", "document", "research",
                "writing", "filesystem",
                "browser", "comms"
            }

        agent_map = {
            "coding": CodingAgent,
            "document": DocumentAgent,
            "research": ResearchAgent,
            "writing": WritingAgent,
            "filesystem": FilesystemAgent,
            "browser": BrowserAgent,
            "comms": CommsAgent,
        }

        for name in active_names:
            cls = agent_map.get(name)
            if cls:
                try:
                    self._agents[name] = cls(
                        self.config,
                        self.profile
                    )
                    logger.debug(
                        f"Loaded agent: {name}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to load {name}: {e}"
                    )

        logger.info(
            f"AgentRegistry ready: "
            f"{list(self._agents.keys())}"
        )

    def select_agent(
        self,
        goal: str,
        scope: str
    ) -> "BaseAgent":
        """
        Select the best agent for a goal.
        Priority order:
          1. First agent whose can_handle() is True
          2. FilesystemAgent as fallback
        """
        # Priority order for disambiguation
        priority = [
            "comms", "browser", "document",
            "research", "writing", "coding",
            "filesystem"
        ]

        for name in priority:
            agent = self._agents.get(name)
            if agent and agent.can_handle(
                goal, scope
            ):
                logger.info(
                    f"Selected agent: {name} "
                    f"for goal: {goal[:50]}"
                )
                return agent

        # Fallback
        fallback = self._agents.get("filesystem")
        logger.info(
            f"Using fallback agent: filesystem"
        )
        return fallback

    def get_agent(self, name: str) -> Optional["BaseAgent"]:
        return self._agents.get(name)

    def list_active(self) -> list[str]:
        return list(self._agents.keys())
