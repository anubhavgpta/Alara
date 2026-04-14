"""Writing capability — draft generation and editing via Gemini."""

import logging

from alara.core.gemini import GeminiClient
from alara.security import permissions

logger = logging.getLogger(__name__)

_DRAFT_PROMPT = """\
Write content based on the following prompt. Produce polished, well-structured output. \
Do not include meta-commentary or explanations — just the content itself.

Prompt: {prompt}
"""

_EDIT_PROMPT = """\
Apply the following editing instructions to the provided text. \
Return only the revised text without meta-commentary or explanations.

Original text:
{original}

Editing instructions:
{instructions}
"""


def draft(prompt: str, client: GeminiClient) -> str:
    """Generate a written draft based on the given prompt.

    Requires user confirmation before making the API call.

    Args:
        prompt: Description of the content to write.
        client: Initialised GeminiClient.

    Returns:
        The generated draft text, or a cancellation message.
    """
    if not permissions.confirm_action("Generate a written draft via Gemini API"):
        logger.debug("Draft generation cancelled by user")
        return "Draft cancelled."

    gemini_prompt = _DRAFT_PROMPT.format(prompt=prompt)
    logger.debug("Generating draft for prompt: %s", prompt)
    return client.chat(gemini_prompt, history=[])


def edit(original: str, instructions: str, client: GeminiClient) -> str:
    """Apply editing instructions to an original piece of text.

    Requires user confirmation before making the API call.

    Args:
        original: The original text to edit.
        instructions: Editing instructions to apply.
        client: Initialised GeminiClient.

    Returns:
        The edited text, or a cancellation message.
    """
    if not permissions.confirm_action("Edit content via Gemini API"):
        logger.debug("Edit cancelled by user")
        return "Edit cancelled."

    gemini_prompt = _EDIT_PROMPT.format(original=original, instructions=instructions)
    logger.debug("Editing content with instructions: %s", instructions)
    return client.chat(gemini_prompt, history=[])
