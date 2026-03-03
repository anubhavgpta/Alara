"""Filesystem capability for file and folder operations via pathlib."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from alara.capabilities.base import BaseCapability, CapabilityResult


class FilesystemCapability(BaseCapability):
    """Execute filesystem-focused operations using pathlib-based primitives."""

    _SUPPORTED = {
        "create_directory",
        "create_file",
        "write_file",
        "read_file",
        "delete_file",
        "delete_directory",
        "move_file",
        "copy_file",
        "list_directory",
        "search_files",
        "check_path_exists",
    }

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        logger.debug("Filesystem operation requested: {} | params={}", operation, params)
        if not self.supports(operation):
            return CapabilityResult.fail(f"Unsupported filesystem operation: {operation}")

        try:
            if operation == "create_directory":
                return self._create_directory(params)
            if operation == "create_file":
                return self._create_file(params)
            if operation == "write_file":
                return self._write_file(params)
            if operation == "read_file":
                return self._read_file(params)
            if operation == "delete_file":
                return self._delete_file(params)
            if operation == "delete_directory":
                return self._delete_directory(params)
            if operation == "move_file":
                return self._move_file(params)
            if operation == "copy_file":
                return self._copy_file(params)
            if operation == "list_directory":
                return self._list_directory(params)
            if operation == "search_files":
                return self._search_files(params)
            if operation == "check_path_exists":
                return self._check_path_exists(params)
            return CapabilityResult.fail(f"Unhandled filesystem operation: {operation}")
        except Exception as exc:
            logger.error("Filesystem exception in {}: {}", operation, exc)
            return CapabilityResult.fail(str(exc))

    def supports(self, operation: str) -> bool:
        return operation in self._SUPPORTED

    def _resolve(self, path: str) -> Path:
        value = str(path or "")
        home = str(Path.home())
        value = value.replace("$env:USERPROFILE", home).replace("$HOME", home)
        resolved = Path(value).expanduser()
        logger.debug("Resolved path '{}' -> '{}'", path, resolved)
        return resolved

    def _create_directory(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        path.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            return CapabilityResult.ok()
        return CapabilityResult.fail(f"Directory was not created: {path}")

    def _create_file(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        content = str(params.get("content", ""))
        if path.exists():
            return CapabilityResult.fail(f"File already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return CapabilityResult.ok()

    def _write_file(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        content = str(params.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return CapabilityResult.ok()

    def _read_file(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        if not path.exists():
            logger.warning("Read requested for missing path: {}", path)
            return CapabilityResult.fail(f"File does not exist: {path}")
        content = path.read_text(encoding="utf-8")
        return CapabilityResult.ok(output=content)

    def _delete_file(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        path.unlink(missing_ok=True)
        return CapabilityResult.ok()

    def _delete_directory(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        if path.exists():
            shutil.rmtree(path)
        return CapabilityResult.ok()

    def _move_file(self, params: dict[str, Any]) -> CapabilityResult:
        source = self._resolve(str(params.get("source", "")))
        destination = self._resolve(str(params.get("destination", "")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return CapabilityResult.ok()

    def _copy_file(self, params: dict[str, Any]) -> CapabilityResult:
        source = self._resolve(str(params.get("source", "")))
        destination = self._resolve(str(params.get("destination", "")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return CapabilityResult.ok()

    def _list_directory(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        if not path.exists() or not path.is_dir():
            logger.warning("List requested on non-directory path: {}", path)
            return CapabilityResult.fail(f"Path is not a directory: {path}")
        names = sorted(item.name for item in path.iterdir())
        return CapabilityResult.ok(output="\n".join(names))

    def _search_files(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        pattern = str(params.get("pattern", ""))
        if not path.exists():
            logger.warning("Search requested on missing base path: {}", path)
            return CapabilityResult.fail(f"Base path does not exist: {path}")
        matches = sorted(str(item.resolve()) for item in path.rglob(pattern))
        return CapabilityResult.ok(output="\n".join(matches))

    def _check_path_exists(self, params: dict[str, Any]) -> CapabilityResult:
        path = self._resolve(str(params.get("path", "")))
        if path.exists():
            return CapabilityResult.ok(output="exists")
        return CapabilityResult.fail(f"path does not exist: {path}")
