"""Coding agent facade — public entry point for all L2 coding intents."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rich_print
from rich.rule import Rule

from alara.coding.aider_backend import AiderBackend
from alara.coding.models import CodingResult, CodingTask
from alara.coding.openhands_backend import OpenHandsBackend
from alara.coding.streaming import stream_to_repl
from alara.core.errors import AlaraError
from alara.security.permissions import confirm_action

if TYPE_CHECKING:
    from alara.core.gemini import GeminiClient
    from alara.core.session import SessionContext

logger = logging.getLogger(__name__)

# Git subcommands that do not modify state and require no confirmation gate.
READ_GIT_OPS: frozenset[str] = frozenset(
    {"status", "diff", "log", "show", "blame"}
)

_FILE_EXTRACT_PROMPT = """\
Extract any file paths explicitly mentioned in the following user request.
Return a JSON array of path strings (relative paths as written by the user).
Return an empty array [] if no specific file paths are mentioned.
Do not include markdown fences — return only the JSON array.

User request: {user_input}
"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _JSON_FENCE_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def _extract_git_subcmd(user_input: str) -> str | None:
    """Return the git subcommand found in user_input, or None."""
    words = user_input.lower().split()
    for i, word in enumerate(words):
        if word == "git" and i + 1 < len(words):
            return words[i + 1].strip(".,;:")
    # Fallback: check if any read/write subcommand word appears directly.
    for word in words:
        candidate = word.strip(".,;:")
        if candidate in READ_GIT_OPS or candidate in (
            "commit", "push", "pull", "merge", "rebase", "reset",
            "branch", "checkout", "add", "stash", "tag",
        ):
            return candidate
    return None


def _extract_files(user_input: str, gemini_client: GeminiClient) -> list[Path]:
    """Ask Gemini to extract file paths from user_input.

    Returns a (possibly empty) list of Path objects.  Paths are returned
    as-is from the user message — callers resolve them relative to workdir.
    """
    try:
        prompt = _FILE_EXTRACT_PROMPT.format(user_input=user_input)
        raw = gemini_client.chat(prompt, history=[])
        cleaned = _strip_fences(raw)
        paths_raw: list = json.loads(cleaned)
        if not isinstance(paths_raw, list):
            return []
        return [Path(p) for p in paths_raw if isinstance(p, str) and p.strip()]
    except Exception as exc:
        logger.warning("File extraction failed: %s", exc)
        return []


async def _stream_subprocess(cmd: list[str], workdir: Path, title: str) -> None:
    """Run *cmd* in *workdir*, streaming stdout+stderr between titled rules."""
    rich_print(Rule(title, style="cyan"))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
        )

        async def _drain(stream: asyncio.StreamReader) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                rich_print(raw.decode("utf-8", errors="replace").rstrip("\n"))

        await asyncio.gather(
            _drain(proc.stdout),  # type: ignore[arg-type]
            _drain(proc.stderr),  # type: ignore[arg-type]
        )
        await proc.wait()

        if proc.returncode != 0:
            logger.warning("%s exited with code %d", cmd[0], proc.returncode)
    except FileNotFoundError:
        rich_print(f"[red]Command not found: {cmd[0]}[/red]")
    except Exception as exc:
        logger.error("_stream_subprocess error (%s): %s", cmd[0], exc)
        rich_print(f"[red]Error: {exc}[/red]")
    rich_print(Rule(style="cyan"))


_GIT_CMD_EXTRACT_PROMPT = """\
Translate the following user request into a single, valid git command.
Return ONLY the git command itself — no explanation, no backticks, no extra text.
The command must start with the word "git".

Examples:
  "git commit with message 'fix bug'"      → git commit -m "fix bug"
  "commit all changes with message init"   → git commit -am "init"
  "show me the last 5 commits"             → git log --oneline -5
  "push to origin main"                    → git push origin main
  "git status"                             → git status

User request: {user_input}
"""


def _extract_git_cmd(user_input: str, gemini_client: "GeminiClient") -> list[str]:
    """Use Gemini to translate natural-language input to a git command.

    Falls back to a heuristic split if Gemini fails or returns something
    that doesn't look like a git command.
    """
    try:
        prompt = _GIT_CMD_EXTRACT_PROMPT.format(user_input=user_input)
        raw = gemini_client.chat(prompt, history=[]).strip()
        if raw.startswith("git"):
            cmd = shlex.split(raw)
            logger.debug("_extract_git_cmd: Gemini → %s", cmd)
            return cmd
        logger.warning("_extract_git_cmd: unexpected Gemini response: %r", raw)
    except Exception as exc:
        logger.warning("_extract_git_cmd: Gemini failed (%s) — using heuristic", exc)

    # Heuristic fallback: take everything from the word "git" onwards.
    words = user_input.strip().split()
    try:
        git_idx = next(i for i, w in enumerate(words) if w.lower() == "git")
        return shlex.split(" ".join(words[git_idx:]))
    except (StopIteration, ValueError):
        subcmd = _extract_git_subcmd(user_input)
        return ["git", subcmd] if subcmd else ["git", "status"]


async def _run_git_direct(
    user_input: str,
    workdir: Path,
    gemini_client: "GeminiClient",
) -> None:
    """Translate *user_input* to a git command via Gemini and run it directly."""
    cmd = _extract_git_cmd(user_input, gemini_client)
    logger.info("_run_git_direct: cmd=%s workdir=%s", cmd, workdir)
    await _stream_subprocess(cmd, workdir, "Git")


_COMMIT_MSG_EXTRACT_PROMPT = """\
Extract the commit message from the following user request.
Return ONLY the commit message text — no explanation, no backticks, no quotes.

Examples:
  "commit all changes with message fix login bug"  → fix login bug
  "git commit initial setup"                       → initial setup
  "stage and commit: refactor auth module"         → refactor auth module

User request: {user_input}
"""


def _extract_commit_message(user_input: str, gemini_client: "GeminiClient") -> str:
    """Use Gemini to extract a commit message from natural-language input.

    Falls back to a heuristic if Gemini fails.
    """
    try:
        prompt = _COMMIT_MSG_EXTRACT_PROMPT.format(user_input=user_input)
        raw = gemini_client.chat(prompt, history=[]).strip()
        if raw:
            logger.debug("_extract_commit_message: Gemini → %r", raw)
            return raw
        logger.warning("_extract_commit_message: Gemini returned empty string")
    except Exception as exc:
        logger.warning("_extract_commit_message: Gemini failed (%s) — using heuristic", exc)

    # Heuristic: drop known trigger words and return the remainder.
    lower = user_input.lower()
    for trigger in ("commit", "git commit", "stage and commit", "commit all"):
        if trigger in lower:
            idx = lower.index(trigger) + len(trigger)
            remainder = user_input[idx:].strip().strip(":-").strip()
            if remainder:
                return remainder
    return user_input.strip()


async def _stage_and_commit(message: str, workdir: Path) -> CodingResult:
    """Stage all changes with ``git add -A`` then commit with *message*."""
    logger.info("_stage_and_commit: workdir=%s message=%r", workdir, message)

    add_proc = await asyncio.create_subprocess_exec(
        "git", "add", "-A",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
    )
    _, add_stderr_bytes = await add_proc.communicate()
    if add_proc.returncode != 0:
        err = add_stderr_bytes.decode("utf-8", errors="replace").strip()
        logger.error("_stage_and_commit: git add failed (rc=%d): %s", add_proc.returncode, err)
        return CodingResult(success=False, summary="", error=err)

    commit_proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
    )
    commit_stdout_bytes, commit_stderr_bytes = await commit_proc.communicate()
    if commit_proc.returncode != 0:
        stderr = commit_stderr_bytes.decode("utf-8", errors="replace").strip()
        stdout = commit_stdout_bytes.decode("utf-8", errors="replace").strip()
        err = stderr or stdout or f"git commit exited with code {commit_proc.returncode}"
        logger.error(
            "_stage_and_commit: git commit failed (rc=%d): %s", commit_proc.returncode, err
        )
        return CodingResult(success=False, summary="", error=err)

    summary = f"Staged all changes and committed: {message}"
    logger.info("_stage_and_commit: success — %s", summary)
    return CodingResult(success=True, summary=summary)


# Trigger words that prefix a shell command in natural language.
_SHELL_TRIGGER_WORDS: frozenset[str] = frozenset(
    {"run", "execute", "launch", "start", "call"}
)


def _parse_shell_cmd(user_input: str) -> list[str] | None:
    """Extract a shell command from natural-language input.

    "run python main.py"  → ["python", "main.py"]
    "execute pytest -v"   → ["pytest", "-v"]
    "python main.py"      → ["python", "main.py"]

    Returns None if the result is empty.
    """
    try:
        parts = shlex.split(user_input)
    except ValueError:
        parts = user_input.split()
    if not parts:
        return None
    if parts[0].lower() in _SHELL_TRIGGER_WORDS and len(parts) > 1:
        parts = parts[1:]
    return parts or None


async def _run_shell_direct(user_input: str, workdir: Path) -> None:
    """Execute a shell command directly in *workdir*."""
    cmd = _parse_shell_cmd(user_input)
    if not cmd:
        rich_print("[yellow]Could not determine shell command from input.[/yellow]")
        return
    logger.info("_run_shell_direct: cmd=%s workdir=%s", cmd, workdir)
    await _stream_subprocess(cmd, workdir, "Shell")


_REVIEW_PROMPT = """\
You are a helpful code assistant. Respond directly to the user's request below.
Be concise and clear. Use plain text; avoid unnecessary preamble.

User request: {user_input}

{file_sections}\
"""


def _run_code_review(
    user_input: str,
    files: list[Path],
    workdir: Path,
    gemini_client: "GeminiClient",
) -> None:
    """Handle code_review by reading files and querying Gemini directly.

    Reads each resolved file path, builds a prompt with their contents, calls
    Gemini, and prints the result.  No aider subprocess is involved.
    """
    file_sections: list[str] = []
    for file_path in files:
        resolved = file_path if file_path.is_absolute() else workdir / file_path
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            file_sections.append(f"### {file_path}\n```\n{content}\n```")
            logger.debug("_run_code_review: read %s (%d chars)", resolved, len(content))
        except FileNotFoundError:
            rich_print(f"[yellow]File not found: {resolved}[/yellow]")
            logger.warning("_run_code_review: file not found: %s", resolved)
        except Exception as exc:
            logger.warning("_run_code_review: could not read %s: %s", resolved, exc)

    file_block = "\n\n".join(file_sections) if file_sections else "(no files provided)"
    prompt = _REVIEW_PROMPT.format(user_input=user_input, file_sections=file_block)

    rich_print(Rule("Code Review", style="cyan"))
    try:
        response = gemini_client.chat(prompt, history=[])
        rich_print(response)
    except Exception as exc:
        logger.error("_run_code_review: Gemini error: %s", exc)
        rich_print(f"[red]Review error: {exc}[/red]")
    rich_print(Rule(style="cyan"))


async def handle(
    intent: str,
    user_input: str,
    session: SessionContext,
    gemini_client: GeminiClient,
    config: dict,
) -> None:
    """Entry point for all coding intents dispatched from core/dispatch.py.

    Handles working directory setup, file extraction, permission gating,
    backend selection and availability check, then delegates to stream_to_repl.

    Args:
        intent:        One of: code_edit, code_create, code_shell, code_git,
                       code_review.
        user_input:    Raw user message.
        session:       Current SessionContext; coding_workdir is persisted here.
        gemini_client: GeminiClient instance for extraction and summarisation.
        config:        Loaded alara.toml dict.
    """
    # --- Working directory management ---
    if "--reset-dir" in user_input:
        session.coding_workdir = None
        user_input = user_input.replace("--reset-dir", "").strip()
        logger.info("Coding workdir reset by user request")

    if session.coding_workdir is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import PathCompleter

        _pt_session: PromptSession = PromptSession()
        raw_dir = (
            await _pt_session.prompt_async(
                "Working directory for this coding session: ",
                completer=PathCompleter(),
            )
        ).strip()
        if not raw_dir:
            rich_print("[yellow]No working directory provided — coding session cancelled.[/yellow]")
            return
        session.coding_workdir = Path(raw_dir).resolve()
        logger.info("Coding workdir set to: %s", session.coding_workdir)

    workdir: Path = session.coding_workdir

    # --- Extract mentioned file paths ---
    files: list[Path] = _extract_files(user_input, gemini_client)

    # --- Confirmation gates ---
    allowed = _check_permission(intent, user_input, workdir)
    if not allowed:
        logger.info(
            "Coding action denied by user (intent=%s workdir=%s)", intent, workdir
        )
        return

    # --- Review, git, and shell run directly — aider/openhands not involved ---
    if intent == "code_review":
        _run_code_review(user_input, files, workdir, gemini_client)
        return

    if intent == "code_git":
        if "commit" in user_input.lower():
            if "-m" in user_input:
                commit_message = user_input.split("-m", 1)[1].strip().strip("'\"")
            else:
                commit_message = _extract_commit_message(user_input, gemini_client)
            logger.info("code_git commit: message=%r workdir=%s", commit_message, workdir)
            result = await _stage_and_commit(commit_message, workdir)
            if not result.success:
                logger.error("Git commit failed: %s", result.error)
                rich_print(f"[red]Git commit failed:[/red] {result.error}")
                return
            rich_print(result.summary)
        else:
            await _run_git_direct(user_input, workdir, gemini_client)
        return

    if intent == "code_shell":
        await _run_shell_direct(user_input, workdir)
        return

    # --- Backend selection ---
    coding_cfg: dict = config.get("coding", {})
    backend_name: str = coding_cfg.get("backend", "aider")

    if backend_name == "aider":
        backend = AiderBackend(
            aider_model=coding_cfg.get("aider_model", "gemini/gemini-2.5-flash"),
            encoding=coding_cfg.get("aider_encoding", "utf-8"),
        )
    elif backend_name == "openhands":
        backend = OpenHandsBackend(
            base_url=coding_cfg.get("openhands_base_url", "http://localhost:3000"),
            timeout_seconds=int(coding_cfg.get("openhands_timeout_seconds", 120)),
        )
    else:
        rich_print(f"[red]Unknown coding backend '{backend_name}'. Check config/alara.toml.[/red]")
        logger.error("Unknown coding backend: %s", backend_name)
        return

    if not await backend.is_available():
        rich_print(
            f"[red]Coding backend '{backend_name}' is not available. "
            f"Install it or start the service and try again.[/red]"
        )
        logger.error("Coding backend not available: %s", backend_name)
        return

    # --- Build task and run ---
    task = CodingTask(
        intent=intent,
        description=user_input,
        workdir=workdir,
        files=files,
        read_only=(intent == "code_review"),
    )

    try:
        await stream_to_repl(backend, task, gemini_client)
    except AlaraError as exc:
        logger.error("Coding agent error: %s", exc)
        rich_print(f"[red]{exc}[/red]")
    except Exception as exc:
        logger.exception("Unexpected coding agent error")
        rich_print(f"[bold red]Coding agent encountered an unexpected error: {exc}[/bold red]")


def _check_permission(intent: str, user_input: str, workdir: Path) -> bool:
    """Return True if the user approves (or the action is gate-free).

    Raises nothing — returns False on denial or gate failure.
    """
    if intent == "code_review":
        return True  # read-only, no gate

    if intent == "code_edit":
        return confirm_action(f"Edit files in {workdir}?")

    if intent == "code_create":
        return confirm_action(f"Create new files in {workdir}?")

    if intent == "code_shell":
        return confirm_action(f"Run shell command in {workdir}?")

    if intent == "code_git":
        subcmd = _extract_git_subcmd(user_input)
        if subcmd and subcmd in READ_GIT_OPS:
            return True  # read-only git op — no gate
        op_label = subcmd or "write"
        return confirm_action(f"Run git {op_label} in {workdir}?")

    # Unknown intent — deny by default.
    logger.warning("_check_permission: unrecognised intent '%s', denying", intent)
    return False
