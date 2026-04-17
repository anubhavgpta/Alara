"""stream_to_repl — drives a coding backend and renders output line-by-line."""

import logging

from rich import print as rich_print
from rich.rule import Rule
from rich.syntax import Syntax

from alara.coding.base import CodingBackend
from alara.coding.models import CodingResult, CodingTask
from alara.core.gemini import GeminiClient

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
Summarize the following coding agent output in 2-3 plain text sentences.
Focus on what was accomplished, any errors encountered, and the overall outcome.
Do not use markdown, bullet points, or headers — plain text only.

Output:
{output}
"""

# Truncate backend output before sending to Gemini to avoid token overflows.
_MAX_OUTPUT_CHARS = 6000


async def stream_to_repl(
    backend: CodingBackend,
    task: CodingTask,
    gemini_client: GeminiClient,
) -> CodingResult:
    """Execute *task* via *backend*, printing each output line as it arrives.

    Steps:
      1. Prints a header rule, then streams backend output line-by-line.
      2. Calls backend.run() with an on_chunk callback that prints each line.
      3. After the backend finishes, asks Gemini to produce a 2-3 sentence summary
         of the full accumulated output and stores it in result.summary.
      4. Prints a footer rule.
      5. Prints the summary via rich.print.
      6. If result.diff is non-empty, renders it via Rich Syntax.
      7. Returns the CodingResult.

    Args:
        backend:       The coding backend (Aider or OpenHands).
        task:          The coding task to execute.
        gemini_client: Used to generate the post-run summary.

    Returns:
        CodingResult with summary populated.
    """
    lines: list[str] = []

    def on_chunk(chunk: str) -> None:
        stripped = chunk.rstrip("\n")
        lines.append(stripped)
        rich_print(stripped)

    logger.info("stream_to_repl: starting backend run (intent=%s)", task.intent)

    rich_print(Rule("Coding Agent", style="cyan"))
    result = await backend.run(task, on_chunk)
    rich_print(Rule(style="cyan"))

    # --- Generate Gemini summary ---
    full_output = "\n".join(lines)
    truncated = full_output[:_MAX_OUTPUT_CHARS]
    if len(full_output) > _MAX_OUTPUT_CHARS:
        truncated += "\n... (output truncated)"

    try:
        summary_prompt = _SUMMARY_PROMPT.format(output=truncated)
        result.summary = gemini_client.chat(summary_prompt, history=[])
        logger.debug("Gemini summary generated (%d chars)", len(result.summary))
    except Exception as exc:
        logger.warning("Summary generation failed: %s", exc)
        result.summary = (
            "Task completed." if result.success else f"Task failed: {result.error}"
        )

    # --- Display summary ---
    rich_print()
    rich_print(f"[bold]Summary:[/bold] {result.summary}")
    rich_print()

    # --- Display diff if present ---
    if result.diff:
        rich_print(Syntax(result.diff, "diff", theme="monokai", line_numbers=False))
        rich_print()

    return result
