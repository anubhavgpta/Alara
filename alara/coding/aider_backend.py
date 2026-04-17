"""Aider coding backend — drives the aider CLI as a subprocess."""

import asyncio
import logging
import os
import shutil
from typing import Callable

from alara.coding.base import CodingBackend
from alara.coding.models import CodingResult, CodingTask
from alara.core.errors import AlaraError
from alara.security import vault

logger = logging.getLogger(__name__)


class AiderBackend(CodingBackend):
    """Coding backend that runs the aider CLI in a subprocess.

    Args:
        aider_model: Model string passed to aider's --model flag.
    """

    def __init__(self, aider_model: str, encoding: str = "utf-8") -> None:
        self._aider_model = aider_model
        self._encoding = encoding

    async def is_available(self) -> bool:
        """Return True if the aider binary is on PATH."""
        return shutil.which("aider") is not None

    async def run(
        self,
        task: CodingTask,
        on_chunk: Callable[[str], None],
    ) -> CodingResult:
        """Invoke aider non-interactively and stream its output.

        Builds the aider command from the task, launches it via
        asyncio.create_subprocess_exec, reads stdout and stderr
        concurrently, and forwards each line to on_chunk.

        Returns:
            CodingResult with success=False and accumulated stderr on
            non-zero exit.  Raises AlaraError on subprocess launch failure.
        """
        cmd: list[str] = [
            "aider",
            "--model", self._aider_model,
            "--encoding", self._encoding,
            "--no-auto-commits",
            "--yes-always",
            "--no-pretty",
            "--no-suggest-shell-commands",
            "--message", task.description,
        ]
        if task.read_only:
            cmd.append("--dry-run")
        for file_path in task.files:
            cmd.append(str(file_path))

        logger.info(
            "AiderBackend.run: workdir=%s model=%s files=%d read_only=%s",
            task.workdir, self._aider_model, len(task.files), task.read_only,
        )

        stderr_lines: list[str] = []

        env = os.environ.copy()
        # Force UTF-8 I/O so aider's Rich output doesn't crash on Windows
        # consoles whose default encoding (e.g. CP1252) can't handle Unicode.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        api_key = vault.get_secret("gemini_api_key")
        if api_key:
            env["GEMINI_API_KEY"] = api_key
            env["GOOGLE_API_KEY"] = api_key

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,   # no console → suppress prompt_toolkit warning
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(task.workdir),
                env=env,
            )
        except Exception as exc:
            logger.error("Failed to launch aider: %s", exc)
            raise AlaraError(f"Could not start aider subprocess: {exc}") from exc

        async def _drain(
            stream: asyncio.StreamReader,
            is_stderr: bool,
        ) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                # Suppress aider's cosmetic Windows-console warning — it fires
                # because aider checks for a Win32 console via the API even when
                # stdin is redirected, and there is nothing the caller can do.
                if "Can't initialize prompt toolkit" in line:
                    continue
                on_chunk(line)
                if is_stderr:
                    stderr_lines.append(line)

        try:
            await asyncio.gather(
                _drain(proc.stdout, False),  # type: ignore[arg-type]
                _drain(proc.stderr, True),   # type: ignore[arg-type]
            )
            await proc.wait()
        except Exception as exc:
            logger.error("Error reading aider output: %s", exc)
            raise AlaraError(f"Aider output stream error: {exc}") from exc

        if proc.returncode != 0:
            error_text = "\n".join(stderr_lines)
            logger.warning(
                "Aider exited with code %d", proc.returncode
            )
            return CodingResult(
                success=False,
                summary="",
                diff=None,
                shell_output=None,
                error=error_text,
            )

        logger.info("Aider completed successfully (exit 0)")
        return CodingResult(
            success=True,
            summary="",
            diff=None,
            shell_output=None,
            error=None,
        )
