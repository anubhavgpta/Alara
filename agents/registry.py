from __future__ import annotations
import json
from pathlib import Path
from typing import Type
from loguru import logger

from agents.base import BaseAgent
from agents.coding_agent import CodingAgent
from agents.document_agent import DocumentAgent
from agents.research_agent import ResearchAgent
from agents.writing_agent import WritingAgent
from agents.filesystem_agent import FilesystemAgent
from agents.browser_agent import BrowserAgent
from agents.comms_agent import CommsAgent

# Map use_case keys from profile.json to agent classes that serve them
USE_CASE_AGENT_MAP: dict[str, list[str]] = {
    "coding_development": [
        "coding", "filesystem", "browser"
    ],
    "research_writing": [
        "research", "writing", "browser", "filesystem"
    ],
    "email_communications": [
        "comms", "filesystem"
    ],
    "productivity": [
        "filesystem", "document", "writing", "browser"
    ],
    "creative_writing": [
        "writing", "document", "filesystem"
    ],
}

# All available agent classes by name
ALL_AGENT_CLASSES: dict[str, Type[BaseAgent]] = {
    "coding":     CodingAgent,
    "document":   DocumentAgent,
    "research":   ResearchAgent,
    "writing":    WritingAgent,
    "filesystem": FilesystemAgent,
    "browser":    BrowserAgent,
    "comms":      CommsAgent,
}

# Priority order for agent selection
AGENT_PRIORITY = [
    "comms", "browser", "document",
    "research", "writing", "coding",
    "filesystem"
]

class AgentRegistry:

    def __init__(
        self,
        config: dict = None,
        profile: dict = None
    ):
        self.config = config or {}
        self.profile = profile or {}

        # Registered agent classes (filtered by use_cases) — populated at startup
        self._registered: dict[
            str, Type[BaseAgent]
        ] = {}

        # Warm agent instances — populated on first use, cached for session
        self._warm: dict[str, BaseAgent] = {}

        self._register_agents()

    def _register_agents(self):
        """
        Phase 1: Register agent classes only.
        No instantiation. Filters by use_cases from profile.json.
        Instant — no API calls.
        """
        use_cases = self.profile.get(
            "use_cases", []
        )

        # Collect agent names enabled by user's use cases
        enabled: set[str] = set()
        for uc in use_cases:
            agents = USE_CASE_AGENT_MAP.get(
                uc, []
            )
            enabled.update(agents)

        # Always include filesystem as fallback
        enabled.add("filesystem")

        # Register in priority order
        for name in AGENT_PRIORITY:
            if name in enabled:
                cls = ALL_AGENT_CLASSES.get(name)
                if cls:
                    self._registered[name] = cls

        logger.info(
            f"AgentRegistry: registered "
            f"{list(self._registered.keys())} "
            f"(lazy, not yet initialized)"
        )

    def _get_or_init(
        self, name: str
    ) -> BaseAgent | None:
        """
        Phase 2: Initialize agent on first use.
        Returns cached instance on subsequent calls.
        """
        if name in self._warm:
            return self._warm[name]

        cls = self._registered.get(name)
        if not cls:
            return None

        logger.info(
            f"AgentRegistry: initializing "
            f"{name} agent (first use)"
        )
        instance = cls(
            config=self.config,
            profile=self.profile
        )
        self._warm[name] = instance
        logger.info(
            f"AgentRegistry: {name} agent "
            f"is now warm"
        )
        return instance

    def select_agent(
        self, goal: str, scope: str
    ) -> BaseAgent | None:
        """
        Select best agent for goal.
        Initializes agent if not yet warm.
        Iterates registered agents in priority order and returns first match.
        """
        # Define file editing keywords for coding agent
        EDIT_KEYWORDS = [
            'add', 'append', 'insert', 'modify',
            'change', 'update', 'refactor', 'rename',
            'delete', 'remove', 'fix', 'implement',
            'create', 'build', 'write', 'generate',
        ]
        
        for name in AGENT_PRIORITY:
            if name not in self._registered:
                continue

            # Peek at can_handle() without full init by using class directly if possible
            cls = self._registered[name]
            try:
                # Try class-level can_handle if implemented as static
                if cls.can_handle(
                    cls, goal, scope
                ):
                    agent = self._get_or_init(
                        name
                    )
                    if agent:
                        logger.info(
                            f"Selected agent: "
                            f"{name} for goal: "
                            f"{goal[:50]}"
                        )
                        return agent
            except Exception:
                # Fall back to instance check
                agent = self._get_or_init(name)
                if agent and agent.can_handle(
                    goal, scope
                ):
                    logger.info(
                        f"Selected agent: "
                        f"{name} for goal: "
                        f"{goal[:50]}"
                    )
                    return agent

        # Enhanced routing logic for filesystem vs coding agent
        if scope == 'filesystem':
            goal_lower = goal.lower()
            has_edit_keyword = any(keyword in goal_lower for keyword in EDIT_KEYWORDS)
            
            if has_edit_keyword:
                # Route to coding agent for file modification tasks
                logger.debug(
                    f"[registry] scope={scope}, edit_keywords_match={has_edit_keyword} → coding"
                )
                agent = self._get_or_init("coding")
                if agent:
                    logger.info(
                        f"Selected agent: coding for goal: {goal[:50]}"
                    )
                    return agent

        # Fallback to filesystem
        logger.warning(
            "No agent matched — falling back "
            "to filesystem agent"
        )
        return self._get_or_init("filesystem")

    def get_registered_names(self) -> list[str]:
        """Return names of registered agents."""
        return list(self._registered.keys())

    def get_warm_names(self) -> list[str]:
        """Return names of initialized agents."""
        return list(self._warm.keys())

    def get_agent(self, name: str) -> BaseAgent | None:
        """Return warm agent instance by name."""
        return self._warm.get(name)

    def list_active(self) -> list[str]:
        """Return names of warm (initialized) agents."""
        return list(self._warm.keys())

    def list_registered(self) -> list[str]:
        """Return names of all registered agents."""
        return list(self._registered.keys())
