"""Research capability — Gemini knowledge-base responses."""

import logging

from alara.core.gemini import GeminiClient
from alara.security import permissions

logger = logging.getLogger(__name__)

_L0_NOTE = "[Research] Gemini knowledge base — no live web search in L0"

_RESEARCH_PROMPT = """\
The user is asking the following research question. Answer it thoroughly, \
drawing on your knowledge. Cite relevant context and be clear about the \
limits of your knowledge where applicable.

Question: {query}
"""


def research(query: str, client: GeminiClient) -> str:
    """Answer a research query using Gemini's knowledge base.

    Requires user confirmation before making the API call.

    Args:
        query: The research question or topic.
        client: Initialised GeminiClient.

    Returns:
        A formatted response string, prefixed with an L0 scope note.
    """
    if not permissions.confirm_action("Send research query to Gemini API"):
        logger.debug("Research query cancelled by user")
        return "Research cancelled."

    prompt = _RESEARCH_PROMPT.format(query=query)
    logger.debug("Sending research query: %s", query)
    response = client.chat(prompt, history=[])
    return f"{_L0_NOTE}\n\n{response}"
