"""
alara/core/intent_engine.py

Ollama-first intent parser for ALARA.
No deterministic classifier is used for primary intent selection.
"""

import json
import os
import re
import time
from typing import Any, Optional

import httpx
from loguru import logger
from pydantic import BaseModel, validator


class Action(BaseModel):
    action: str
    params: dict[str, Any]
    confidence: float
    raw_text: str

    @validator("action")
    def validate_action(cls, v):
        valid_actions = {
            "open_app",
            "close_app",
            "switch_app",
            "minimize_window",
            "maximize_window",
            "close_window",
            "take_screenshot",
            "open_file",
            "open_folder",
            "search_files",
            "run_command",
            "browser_new_tab",
            "browser_navigate",
            "browser_search",
            "browser_close_tab",
            "vscode_open_file",
            "vscode_new_terminal",
            "vscode_search",
            "volume_up",
            "volume_down",
            "volume_mute",
            "lock_screen",
            "unknown",
        }
        if v not in valid_actions:
            logger.warning(f"Invalid action '{v}', defaulting to 'unknown'")
            return "unknown"
        return v

    @validator("confidence")
    def validate_confidence(cls, v):
        return max(0.0, min(1.0, float(v)))


SYSTEM_PROMPT = """
You are ALARA's intent classifier for Windows voice commands.
Return one JSON object only. No markdown. No prose.

Allowed actions:
open_app, close_app, switch_app,
minimize_window, maximize_window, close_window, take_screenshot,
open_file, open_folder, search_files,
run_command,
browser_new_tab, browser_navigate, browser_search, browser_close_tab,
vscode_open_file, vscode_new_terminal, vscode_search,
volume_up, volume_down, volume_mute, lock_screen,
unknown

Return exactly:
{"action":"<allowed_action>","params":{},"confidence":0.95}

Rules:
- Normalize app names: "vs code" -> "vscode", "chrome" -> "google chrome", "terminal" -> "windows terminal".
- Terminal/dev commands (git, npm, pip, python, pytest, docker, docker-compose, uv, pnpm, yarn) should be run_command.
- "search for X" defaults to browser_search unless editor/code context indicates vscode_search.
- If command includes a domain/url (e.g. google.com), use browser_navigate with https://.
- If command asks to open a specific file in VS Code, use vscode_open_file.
- If command asks to open a specific file without VS Code context, use open_file.
- If unsupported (weather/jokes/email/music etc.), use unknown with a short reason.
- confidence in [0, 1].
""".strip()


class IntentEngine:
    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "mistral")
        self.max_retries = 4
        self.retry_delay = 2
        self._check_ollama()

    def _check_ollama(self):
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=3)
            models = [m["name"] for m in resp.json().get("models", [])]
            model_base = self.model.split(":")[0]
            if any(model_base in m for m in models):
                logger.success(f"Ollama ready model={self.model}")
            else:
                logger.warning(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
        except Exception:
            logger.error("Cannot connect to Ollama. Start Ollama and retry.")

    def _make_action(self, action: str, params: dict[str, Any], confidence: float, raw_text: str) -> Action:
        return Action(action=action, params=params, confidence=confidence, raw_text=raw_text)

    def _normalize_action(self, parsed: dict, transcription: str) -> Action:
        original_action = str(parsed.get("action", "unknown")).strip()
        action = original_action
        params = parsed.get("params", {})
        if not isinstance(params, dict):
            params = {}
        confidence = parsed.get("confidence", 0.5)
        t = transcription.strip().lower()

        valid_actions = {
            "open_app",
            "close_app",
            "switch_app",
            "minimize_window",
            "maximize_window",
            "close_window",
            "take_screenshot",
            "open_file",
            "open_folder",
            "search_files",
            "run_command",
            "browser_new_tab",
            "browser_navigate",
            "browser_search",
            "browser_close_tab",
            "vscode_open_file",
            "vscode_new_terminal",
            "vscode_search",
            "volume_up",
            "volume_down",
            "volume_mute",
            "lock_screen",
            "unknown",
        }

        # Canonicalize common non-schema actions produced by LLM.
        if action not in valid_actions:
            known_apps = {"vscode", "google chrome", "chrome", "firefox", "notepad", "slack", "terminal", "windows terminal"}
            action_l = action.lower()
            if action_l in known_apps:
                if t.startswith("open ") or t.startswith("launch "):
                    action = "open_app"
                    params = {"app_name": action_l}
                elif t.startswith("close ") or t.startswith("shutdown "):
                    action = "close_app"
                    params = {"app_name": action_l}
                elif t.startswith("switch to "):
                    action = "switch_app"
                    params = {"app_name": action_l}
                else:
                    action = "open_app"
                    params = {"app_name": action_l}
            elif action_l == "vscode_open_url":
                action = "browser_navigate"
            else:
                action = "unknown"

        # Normalize param key aliases.
        if "app" in params and "app_name" not in params:
            params["app_name"] = params.pop("app")
        if "file" in params:
            if action == "open_file" and "path" not in params:
                params["path"] = params.pop("file")
            elif action == "vscode_open_file" and "query" not in params:
                params["query"] = params.pop("file")
            elif "path" not in params and "query" not in params:
                params["path"] = params.pop("file")

        # Fix obvious misroutes with transcription context.
        if action == "run_command" and not params.get("command"):
            target = re.sub(r"^(open|launch|close|shutdown|switch to)\s+", "", t).strip()
            if t.startswith("open ") or t.startswith("launch "):
                action = "open_app"
                params = {"app_name": target}
            elif t.startswith("close ") or t.startswith("shutdown "):
                action = "close_app"
                params = {"app_name": target}
            elif t.startswith("switch to "):
                action = "switch_app"
                params = {"app_name": target}

        if action == "run_command" and str(params.get("command", "")).strip().lower() == "cls":
            params["command"] = "clear"
        if action == "run_command" and str(params.get("command", "")).strip().lower() == "exit" and "terminal" in t:
            action = "close_app"
            params = {"app_name": "windows terminal"}
        if action == "run_command":
            cmd_val = str(params.get("command", "")).strip()
            if t.startswith("open ") and cmd_val and "." in cmd_val:
                action = "open_file"
                params = {"path": cmd_val}

        if action == "open_file" and "path" not in params:
            m = re.search(r"([a-zA-Z0-9_\-]+\.[a-zA-Z0-9_]+)", transcription)
            if m:
                params["path"] = m.group(1)

        if action == "vscode_open_file" and "query" not in params:
            m = re.search(r"([a-zA-Z0-9_\-]+\.[a-zA-Z0-9_]+)", transcription)
            if m:
                params["query"] = m.group(1)

        if action == "browser_search":
            q = str(params.get("query", "")).lower()
            if "files" in q:
                action = "search_files"
                if "python" in q:
                    params["query"] = "*.py"
                elif "readme" in q:
                    params["query"] = "README*"
            if "search for readme files" in t:
                action = "search_files"
                params["query"] = "README*"
            code_terms = ("function", "class", "method", "definition", "import")
            if any(term in t for term in code_terms):
                action = "vscode_search"
                if t.startswith("find the "):
                    params["query"] = transcription.lower().replace("find the ", "", 1).strip()
                elif t.startswith("find "):
                    params["query"] = transcription.lower().replace("find ", "", 1).strip()
                elif t.startswith("search for "):
                    params["query"] = transcription.replace("search for ", "", 1).strip()

        # Derive app target directly from command phrase when app actions are selected.
        if action in {"open_app", "close_app", "switch_app"}:
            target = ""
            if t.startswith("open ") or t.startswith("launch "):
                target = re.sub(r"^(open|launch)\s+", "", t).strip()
            elif t.startswith("close ") or t.startswith("shutdown "):
                target = re.sub(r"^(close|shutdown)\s+", "", t).strip()
            elif t.startswith("switch to "):
                target = re.sub(r"^switch to\s+", "", t).strip()
            target = re.sub(r"\s+app$", "", target).strip()
            if target:
                params["app_name"] = target

        if action == "unknown":
            if t.startswith("switch to "):
                action = "switch_app"
                params = {"app_name": t.replace("switch to ", "", 1).strip()}
            elif t.startswith("open ") or t.startswith("launch "):
                target = re.sub(r"^(open|launch)\s+", "", t).strip()
                if "." in target and ("vs code" in t or "vscode" in t):
                    action = "vscode_open_file"
                    params = {"query": target.split()[0]}
                elif "." in target:
                    action = "open_file"
                    params = {"path": target.split()[0]}
                elif target == "github":
                    action = "browser_navigate"
                    params = {"url": "https://github.com"}
                else:
                    action = "open_app"
                    params = {"app_name": target}
            elif t.startswith("close ") or t.startswith("shutdown "):
                target = re.sub(r"^(close|shutdown)\s+", "", t).strip()
                action = "close_app"
                params = {"app_name": target}

        # App name normalization.
        if action in {"open_app", "close_app", "switch_app"}:
            app = str(params.get("app_name", "")).strip().lower()
            aliases = {
                "vs code": "vscode",
                "visual studio code": "vscode",
                "chrome": "google chrome",
                "terminal": "windows terminal",
            }
            if app in aliases:
                params["app_name"] = aliases[app]

        if action in {"volume_up", "volume_down"} and "amount" not in params:
            params["amount"] = 10

        if action == "unknown" and "reason" not in params:
            params["reason"] = "unsupported or unclear command"

        return self._make_action(action, params, float(confidence), transcription)

    def _extract_json(self, raw_content: str) -> Optional[dict]:
        candidates = [
            raw_content,
            raw_content.strip("`").replace("```json", "").replace("```", ""),
            raw_content.replace("'", '"'),
        ]
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if match:
            candidates.append(match.group(0))

        for c in candidates:
            try:
                return json.loads(c)
            except Exception:
                continue
        return None

    def _query_ollama(self, transcription: str) -> str:
        response = httpx.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.0,
                    "num_predict": 180,
                    "top_p": 0.9,
                },
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcription},
                ],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()

    def parse(self, transcription: str) -> Action:
        if not transcription.strip():
            return self._make_action("unknown", {"reason": "empty transcription"}, 0.0, transcription)

        last_error = "unknown error"

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"Parsing intent with Ollama: attempt {attempt}/{self.max_retries}")
                raw = self._query_ollama(transcription)
                parsed = self._extract_json(raw)
                if parsed is None:
                    last_error = "invalid JSON from LLM"
                    time.sleep(0.5)
                    continue

                action = self._normalize_action(parsed, transcription)
                logger.info(
                    f"Intent (ollama): {action.action} | params={action.params} | "
                    f"confidence={action.confidence:.2f}"
                )
                return action

            except httpx.HTTPStatusError as e:
                last_error = f"ollama error: {e.response.status_code}"
                if e.response.status_code >= 500 and attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
                    continue
                break
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    time.sleep(1)
                    continue
                break

        logger.error(f"Intent engine failed after retries: {last_error}")
        return self._make_action("unknown", {"reason": last_error}, 0.0, transcription)
