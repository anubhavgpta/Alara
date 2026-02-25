"""
alara/core/intent_engine.py

Parses a voice transcription into a structured Action object.
Uses Ollama running locally — no API key, no internet, completely free.

Ollama setup (one time):
  1. Download from https://ollama.com/download and install
  2. Run: ollama pull llama3.1
  3. Ollama runs as a background service on http://localhost:11434
"""

import os
import json
import httpx
from pydantic import BaseModel
from loguru import logger
from typing import Any


# ── Action Schema ─────────────────────────────────────────────────────────────

class Action(BaseModel):
    action: str
    params: dict[str, Any]
    confidence: float
    raw_text: str


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are the intent engine for ALARA — an Ambient Language & Reasoning Assistant
that controls a Windows computer by voice.

Your ONLY job: parse a voice command into a JSON action object.
You MUST respond with valid JSON only. No explanation. No markdown. No code blocks. Just raw JSON.

## Available Actions

App Control:
- open_app        { "app_name": string }
- close_app       { "app_name": string }
- switch_app      { "app_name": string }

Window Management:
- minimize_window {}
- maximize_window {}
- close_window    {}
- take_screenshot {}

File System:
- open_file       { "path": string }
- open_folder     { "path": string }
- search_files    { "query": string, "location": string }

Terminal:
- run_command     { "command": string }

Browser:
- browser_new_tab   {}
- browser_navigate  { "url": string }
- browser_search    { "query": string }
- browser_close_tab {}

VS Code:
- vscode_open_file    { "query": string }
- vscode_new_terminal {}
- vscode_search       { "query": string }

System:
- volume_up    { "amount": 10 }
- volume_down  { "amount": 10 }
- volume_mute  {}
- lock_screen  {}

Unknown:
- unknown      { "reason": string }

## Response Format — ALWAYS use this exact JSON structure:
{"action": "<name>", "params": {}, "confidence": 0.95}

## Rules:
- Normalize app names: "vs code" → "vscode", "terminal" → "windows terminal"
- confidence 0.9-1.0 = certain, 0.6-0.9 = likely, 0.4-0.6 = unsure, below 0.4 → use unknown
- If unsure, use the unknown action with a reason
- Never invent actions not listed above
""".strip()


# ── Intent Engine ─────────────────────────────────────────────────────────────

class IntentEngine:
    """
    Calls Ollama's local HTTP API to parse voice commands into Actions.
    Ollama must be running: https://ollama.com/download

    Usage:
        engine = IntentEngine()
        action = engine.parse("open VS Code and switch to the test file")
    """

    def __init__(self):
        self.host  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1")
        self._check_ollama()

    def _check_ollama(self):
        """Verify Ollama is running and the model is available."""
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=3)
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = self.model.split(":")[0]
            available = any(model_base in m for m in models)

            if not available:
                logger.warning(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Run: ollama pull {self.model}"
                )
            else:
                logger.success(f"Ollama ready — model={self.model}")

        except httpx.ConnectError:
            logger.error(
                "Cannot connect to Ollama. "
                "Make sure Ollama is installed and running: https://ollama.com/download"
            )

    def parse(self, transcription: str) -> Action:
        """
        Parse a transcription into a structured Action.
        Always returns an Action — falls back to 'unknown' on any error.
        """
        if not transcription.strip():
            return Action(action="unknown", params={"reason": "empty transcription"},
                          confidence=0.0, raw_text=transcription)

        try:
            logger.debug(f"Parsing intent for: '{transcription}'")

            response = httpx.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,    # low = more deterministic JSON
                        "num_predict": 150,    # cap tokens — we only need short JSON
                    },
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": transcription},
                    ],
                },
                timeout=60.0,   # local LLM can be slow on first token
            )
            response.raise_for_status()

            raw_content = response.json()["message"]["content"].strip()
            logger.debug(f"Ollama raw response: {raw_content}")

            # Strip accidental markdown code fences if present
            raw_content = raw_content.strip("`")
            if raw_content.startswith("json"):
                raw_content = raw_content[4:].strip()

            parsed = json.loads(raw_content)

            action = Action(
                action=parsed.get("action", "unknown"),
                params=parsed.get("params", {}),
                confidence=float(parsed.get("confidence", 0.5)),
                raw_text=transcription,
            )

            logger.info(
                f"Intent: {action.action} | params={action.params} | "
                f"confidence={action.confidence:.2f}"
            )
            return action

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Ollama: {e}\nRaw: {raw_content!r}")
            return Action(action="unknown", params={"reason": "invalid JSON from LLM"},
                          confidence=0.0, raw_text=transcription)
        except Exception as e:
            logger.error(f"Intent engine error: {e}")
            return Action(action="unknown", params={"reason": str(e)},
                          confidence=0.0, raw_text=transcription)
