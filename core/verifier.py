"""Verification module for checking real-world state after each execution step."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from alara.capabilities.base import CapabilityResult
from alara.capabilities.system import SystemCapability
from alara.schemas.task_graph import Step


@dataclass
class VerificationResult:
    passed: bool
    method: str
    detail: str


class Verifier:
    """Validate that an executed step produced the expected outcome."""

    def __init__(self) -> None:
        self.system_capability = SystemCapability()

    def verify(
        self, step: Step, capability_result: CapabilityResult
    ) -> VerificationResult:
        method = (step.verification_method or "none").strip()
        logger.debug("Verifier method={} for step {}", method, step.id)

        try:
            if method == "check_path_exists":
                result = self._check_path_exists(step)
            elif method == "check_exit_code_zero":
                result = self._check_exit_code_zero(capability_result)
            elif method == "check_process_running":
                result = self._check_process_running(step, capability_result)
            elif method == "check_file_contains":
                result = self._check_file_contains(step)
            elif method == "check_directory_not_empty":
                result = self._check_directory_not_empty(step)
            elif method == "check_port_open":
                result = self._check_port_open(step)
            elif method == "check_output_contains":
                result = self._check_output_contains(step, capability_result)
            elif method == "none":
                result = VerificationResult(True, method, "No verification required")
            else:
                logger.warning("Unknown verification method: {}", method)
                result = VerificationResult(
                    True, method, "Unknown verification method — skipped"
                )
            logger.debug(
                "Verification result for step {}: passed={} detail={}",
                step.id,
                result.passed,
                result.detail,
            )
            return result
        except Exception as exc:
            detail = f"Verification exception: {exc}"
            logger.warning("Verification failed with exception for step {}: {}", step.id, exc)
            return VerificationResult(False, method, detail)

    def _resolve(self, path: str) -> Path:
        value = str(path or "")
        home = str(Path.home())
        value = value.replace("$env:USERPROFILE", home).replace("$HOME", home)
        return Path(value).expanduser()

    def _check_path_exists(self, step: Step) -> VerificationResult:
        path = self._resolve(str(step.params.get("path", "")))
        passed = path.exists()
        detail = f"Path exists: {path}" if passed else f"Path not found: {path}"
        return VerificationResult(passed, "check_path_exists", detail)

    def _check_exit_code_zero(self, capability_result: CapabilityResult) -> VerificationResult:
        returncode = capability_result.metadata.get("returncode")
        passed = returncode == 0
        return VerificationResult(passed, "check_exit_code_zero", f"Exit code: {returncode}")

    def _check_process_running(
        self, step: Step, capability_result: CapabilityResult
    ) -> VerificationResult:
        process_name = str(step.params.get("process_name", "")).strip()
        output = (capability_result.output or "").lower()
        if "running" in output:
            return VerificationResult(
                True,
                "check_process_running",
                f"Process {process_name} is running",
            )

        fresh = self.system_capability.execute("check_process", {"process_name": process_name})
        if fresh.success and (fresh.output or "").lower() == "running":
            return VerificationResult(
                True,
                "check_process_running",
                f"Process {process_name} is running",
            )
        return VerificationResult(
            False,
            "check_process_running",
            f"Process {process_name} not running",
        )

    def _check_file_contains(self, step: Step) -> VerificationResult:
        path = self._resolve(str(step.params.get("path", "")))
        expected = step.params.get("expected_content")
        if expected is None:
            expected = step.params.get("content", "")
        expected = str(expected)
        if not path.exists():
            return VerificationResult(False, "check_file_contains", f"Path not found: {path}")
        text = path.read_text(encoding="utf-8")
        passed = expected in text
        detail = (
            "File contains expected content"
            if passed
            else "File content not found"
        )
        return VerificationResult(passed, "check_file_contains", detail)

    def _check_directory_not_empty(self, step: Step) -> VerificationResult:
        path = self._resolve(str(step.params.get("path", "")))
        if not path.exists() or not path.is_dir():
            return VerificationResult(False, "check_directory_not_empty", "Directory is empty")
        entries = list(path.iterdir())
        if entries:
            return VerificationResult(
                True,
                "check_directory_not_empty",
                f"Directory has {len(entries)} entries",
            )
        return VerificationResult(False, "check_directory_not_empty", "Directory is empty")

    def _check_port_open(self, step: Step) -> VerificationResult:
        host = str(step.params.get("host", "localhost"))
        port = int(step.params.get("port"))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            is_open = sock.connect_ex((host, port)) == 0
        detail = f"Port {port} is open" if is_open else f"Port {port} is closed"
        return VerificationResult(is_open, "check_port_open", detail)

    def _check_output_contains(
        self, step: Step, capability_result: CapabilityResult
    ) -> VerificationResult:
        expected = str(step.params.get("expected_content", ""))
        if not expected:
            return VerificationResult(
                True,
                "check_output_contains",
                "Output contains expected content",
            )
        output = capability_result.output or ""
        passed = expected in output
        detail = (
            "Output contains expected content" if passed else "Expected output not found"
        )
        return VerificationResult(passed, "check_output_contains", detail)
