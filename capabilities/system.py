"""System capability for environment and process checks."""

from __future__ import annotations

import os
import subprocess
from typing import Any

import psutil
from loguru import logger

from alara.capabilities.base import BaseCapability, CapabilityResult


class SystemCapability(BaseCapability):
    """Execute system-oriented operations."""

    _SUPPORTED = {"get_env_var", "set_env_var", "check_process"}

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        logger.debug("System operation requested: {} | params={}", operation, params)
        if not self.supports(operation):
            return CapabilityResult.fail(f"Unsupported system operation: {operation}")

        try:
            if operation == "get_env_var":
                return self._get_env_var(params)
            if operation == "set_env_var":
                return self._set_env_var(params)
            if operation == "check_process":
                return self._check_process(params)
            return CapabilityResult.fail(f"Unhandled system operation: {operation}")
        except Exception as exc:
            logger.error("System capability exception in {}: {}", operation, exc)
            return CapabilityResult.fail(str(exc))

    def supports(self, operation: str) -> bool:
        return operation in self._SUPPORTED

    def _get_env_var(self, params: dict[str, Any]) -> CapabilityResult:
        name = str(params.get("name", "")).strip()
        value = os.environ.get(name)

        if name == "HOME" and not value:
            value = os.environ.get("USERPROFILE")
            if not value:
                home_drive = os.environ.get("HOMEDRIVE", "")
                home_path = os.environ.get("HOMEPATH", "")
                if home_drive and home_path:
                    value = f"{home_drive}{home_path}"

        if value is None:
            return CapabilityResult.fail(f"Environment variable not found: {name}")
        return CapabilityResult.ok(output=value)

    def _set_env_var(self, params: dict[str, Any]) -> CapabilityResult:
        name = str(params.get("name", "")).strip()
        value = str(params.get("value", ""))
        os.environ[name] = value
        return CapabilityResult.ok()

    def _check_process(self, params: dict[str, Any]) -> CapabilityResult:
        process_name = str(params.get("process_name", "")).strip()
        if not process_name:
            return CapabilityResult.fail("Missing required parameter: process_name")

        command = f'tasklist /FI "IMAGENAME eq {process_name}"'
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
        if process_name.lower() in output.lower():
            return CapabilityResult.ok(output="running", metadata={"raw_output": output})

        # Fallback for environments where tasklist output can differ.
        for process in psutil.process_iter(attrs=["name"]):
            name = (process.info.get("name") or "").lower()
            if name == process_name.lower():
                return CapabilityResult.ok(output="running", metadata={"raw_output": output})

        return CapabilityResult.fail(
            error=f"Process not running: {process_name}",
            metadata={"raw_output": output},
        )
