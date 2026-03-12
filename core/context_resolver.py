"""Context resolver for ALARA - resolves pronouns and references using session history."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
import google.genai as genai


class ContextResolver:
    """
    Resolves pronouns and references in a raw goal string using prior session history.
    """

    REFERENCE_TRIGGERS = [
        "it", "its", "that", "this",
        "the file", "the folder", "the directory",
        "there", "that path", "the same",
        "the result", "the output"
    ]

    def __init__(self, config: dict):
        """
        Initialize the context resolver.
        
        Args:
            config: Configuration dictionary containing model and API settings
        """
        self.config = config
        self.model = config.get('model', 'gemini-2.5-flash')
        api_key = config.get('api_key', '')
        self.client = genai.Client(api_key=api_key)

    def needs_resolution(self, raw_input: str) -> bool:
        """
        Quick check: does this input contain any reference triggers?
        
        Args:
            raw_input: The raw input string to check
            
        Returns:
            True if the input contains reference triggers, False otherwise
        """
        lower = raw_input.lower()
        return any(
            trigger in lower.split()
            or f" {trigger} " in f" {lower} "
            for trigger in self.REFERENCE_TRIGGERS
        )

    def resolve(self, raw_input: str, session_history: list[dict]) -> str:
        """
        If raw_input contains ambiguous references, use Gemini to resolve them using session history context.
        
        Args:
            raw_input: The raw input string that may contain ambiguous references
            session_history: List of recent session entries for context
            
        Returns:
            The resolved string, or raw_input unchanged if no resolution needed
        """
        if not self.needs_resolution(raw_input):
            return raw_input

        if not session_history:
            return raw_input

        # Build context from history
        history_text = self._format_history(session_history)

        prompt = f"""
You are a context resolver for an AI assistant.

The user just said:
"{raw_input}"

Prior conversation history (most recent first):
{history_text}

Task: If the user's message contains ambiguous references (like "it", "there", "the file", "that", "the same place"), resolve them using the history.

Replace vague references with the specific, concrete values from history (file paths, URLs, names, etc).

If nothing needs resolving, return the original message exactly.

Return ONLY the resolved message string.
No explanation, no quotes, no markdown.
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            resolved = response.text.strip()

            # Safety: if Gemini returns something wildly different, fall back
            if len(resolved) > len(raw_input) * 5:
                logger.warning("Context resolution returned unusually long result, falling back to original")
                return raw_input

            logger.debug(f"Context resolution successful: '{raw_input}' → '{resolved}'")
            return resolved

        except Exception as e:
            logger.error(f"Context resolution failed: {e}")
            return raw_input

    def _format_history(self, history: list[dict]) -> str:
        """
        Format session history for context resolution.
        
        Args:
            history: List of session history dictionaries
            
        Returns:
            Formatted string containing the history
        """
        lines = []
        for i, entry in enumerate(history[:5]):
            goal = entry.get('goal', '')
            output = entry.get('output', '')
            paths = entry.get('paths', [])

            line = f"{i+1}. Goal: {goal}"
            if paths:
                line += f"\n   Paths: {', '.join(paths)}"
            if output:
                line += f"\n   Output: {output[:200]}"
            lines.append(line)
        return "\n".join(lines)
