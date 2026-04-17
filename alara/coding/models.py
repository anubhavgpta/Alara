"""Data models for the Alara coding agent."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodingTask:
    """Describes a single coding job to be executed by a backend.

    Attributes:
        intent:      One of: code_edit, code_create, code_shell, code_git, code_review.
        description: Raw user instruction forwarded to the backend as-is.
        workdir:     Absolute path to the project root the backend should operate in.
        files:       Specific files the user mentioned; may be empty.
        read_only:   True for code_review — backends must not write files.
    """

    intent: str
    description: str
    workdir: Path
    files: list[Path] = field(default_factory=list)
    read_only: bool = False


@dataclass
class CodingResult:
    """Result returned by a coding backend after a task completes.

    Attributes:
        success:      True when the backend exited cleanly.
        summary:      2-3 sentence Gemini-generated plain-text summary.
        diff:         Unified diff string, or None if unavailable.
        shell_output: Raw terminal output for shell / git tasks, or None.
        error:        Error message when success is False, else None.
    """

    success: bool
    summary: str
    diff: str | None = None
    shell_output: str | None = None
    error: str | None = None
