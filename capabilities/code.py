"""Code capability for reading, analyzing, and editing source code files."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from capabilities.base import BaseCapability, CapabilityResult


class CodeCapability(BaseCapability):
    """Handle code-related operations: read, analyze, edit, and summarize code files."""

    def supports(self, operation: str) -> bool:
        """Return True for all supported code operations."""
        return operation in {
            "read_file",
            "read_lines", 
            "analyze_structure",
            "edit_file",
            "append_to_file",
            "insert_after_line",
            "summarize_file",
            "scan_project",
            "check_contains",
        }

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        """Execute the requested code operation."""
        try:
            if operation == "read_file":
                return self._read_file(params)
            elif operation == "read_lines":
                return self._read_lines(params)
            elif operation == "analyze_structure":
                return self._analyze_structure(params)
            elif operation == "edit_file":
                return self._edit_file(params)
            elif operation == "append_to_file":
                return self._append_to_file(params)
            elif operation == "insert_after_line":
                return self._insert_after_line(params)
            elif operation == "summarize_file":
                return self._summarize_file(params)
            elif operation == "scan_project":
                return self._scan_project(params)
            elif operation == "check_contains":
                return self._check_contains(params)
            else:
                return CapabilityResult.fail(f"Unsupported operation: {operation}")
        except Exception as exc:
            return CapabilityResult.fail(f"Code operation failed: {exc}")

    def _resolve(self, path: str) -> Path:
        """Resolve path with environment variable expansion and anchoring."""
        path_obj = Path(path)
        
        # Expand environment variables
        expanded = os.path.expandvars(path)
        path_obj = Path(expanded)
        
        # Expand ~ to home
        if path_obj.name.startswith("~"):
            path_obj = Path.home() / path_obj.name[1:]
        
        # If relative, anchor to home directory
        if not path_obj.is_absolute():
            path_obj = Path.home() / path_obj
        
        return path_obj

    def _read_file(self, params: dict[str, Any]) -> CapabilityResult:
        """Read the full content of a file."""
        path = self._resolve(params["path"])
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="latin-1")
            except UnicodeDecodeError:
                return CapabilityResult.fail(f"Could not decode file: {path}")
        
        metadata = {
            "path": str(path),
            "line_count": len(content.splitlines()),
            "size_bytes": len(content.encode("utf-8")),
            "encoding": "utf-8"
        }
        
        return CapabilityResult.ok(output=content, metadata=metadata)

    def _read_lines(self, params: dict[str, Any]) -> CapabilityResult:
        """Read a specific line range (1-indexed, inclusive)."""
        path = self._resolve(params["path"])
        start = params["start"]
        end = params["end"]
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="latin-1")
            except UnicodeDecodeError:
                return CapabilityResult.fail(f"Could not decode file: {path}")
        
        lines = content.splitlines()
        total_lines = len(lines)
        
        # Convert 1-indexed to 0-indexed and clamp bounds
        start_idx = max(0, start - 1)
        end_idx = min(total_lines, end)
        
        selected_lines = lines[start_idx:end_idx]
        output = "\n".join(selected_lines)
        
        metadata = {
            "path": str(path),
            "start": start,
            "end": end,
            "total_lines": total_lines
        }
        
        return CapabilityResult.ok(output=output, metadata=metadata)

    def _analyze_structure(self, params: dict[str, Any]) -> CapabilityResult:
        """Analyze Python file structure using AST."""
        path = self._resolve(params["path"])
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        
        # Check if it's a Python file
        if not path.suffix == ".py":
            # Return basic summary for non-Python files
            lines = content.splitlines()
            preview = "\n".join(lines[:20])
            output = f"File: {path.name}\nType: {path.suffix or 'unknown'}\nLines: {len(lines)}\n\nPreview:\n{preview}"
            metadata = {"path": str(path), "language": path.suffix or "unknown", "class_count": 0, "function_count": 0}
            return CapabilityResult.ok(output=output, metadata=metadata)
        
        # Parse Python AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Fallback to line-based summary for invalid Python
            lines = content.splitlines()
            preview = "\n".join(lines[:20])
            output = f"File: {path.name}\nType: Python (invalid syntax)\nLines: {len(lines)}\n\nPreview:\n{preview}"
            metadata = {"path": str(path), "language": "python", "class_count": 0, "function_count": 0}
            return CapabilityResult.ok(output=output, metadata=metadata)
        
        # Extract structure
        imports = []
        classes = []
        functions = []
        constants = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"from {module} import {alias.name}")
            elif isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                classes.append(f"{node.name}({len(methods)} methods)")
            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants.append(target.id)
        
        # Build summary
        output_parts = [
            f"File: {path.name}",
            f"Type: Python",
            f"Classes: {len(classes)}",
            f"Functions: {len(functions)}",
            f"Imports: {len(imports)}",
            ""
        ]
        
        if imports:
            output_parts.append("Imports:")
            output_parts.extend(f"  {imp}" for imp in imports[:10])
            if len(imports) > 10:
                output_parts.append(f"  ... and {len(imports) - 10} more")
            output_parts.append("")
        
        if classes:
            output_parts.append("Classes:")
            output_parts.extend(f"  {cls}" for cls in classes)
            output_parts.append("")
        
        if functions:
            output_parts.append("Functions:")
            output_parts.extend(f"  {fn}" for fn in functions)
            output_parts.append("")
        
        if constants:
            output_parts.append("Constants:")
            output_parts.extend(f"  {const}" for const in constants[:10])
            if len(constants) > 10:
                output_parts.append(f"  ... and {len(constants) - 10} more")
        
        output = "\n".join(output_parts)
        
        metadata = {
            "path": str(path),
            "language": "python",
            "class_count": len(classes),
            "function_count": len(functions)
        }
        
        return CapabilityResult.ok(output=output, metadata=metadata)

    def _edit_file(self, params: dict[str, Any]) -> CapabilityResult:
        """Replace the first occurrence of old_content with new_content."""
        path = self._resolve(params["path"])
        old_content = params["old_content"]
        new_content = params["new_content"]
        description = params.get("description", "")
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        
        if old_content not in content:
            return CapabilityResult.fail(
                f"Edit target not found in {path}. The file may have changed. "
                f"Re-read the file and retry."
            )
        
        updated_content = content.replace(old_content, new_content, 1)
        
        try:
            path.write_text(updated_content, encoding="utf-8")
        except UnicodeEncodeError:
            path.write_text(updated_content, encoding="latin-1")
        
        chars_removed = len(old_content)
        chars_added = len(new_content)
        
        output = f"Edited {path}: replaced target content"
        
        metadata = {
            "path": str(path),
            "description": description,
            "chars_removed": chars_removed,
            "chars_added": chars_added
        }
        
        return CapabilityResult.ok(output=output, metadata=metadata)

    def _append_to_file(self, params: dict[str, Any]) -> CapabilityResult:
        """Append content to the end of an existing file."""
        path = self._resolve(params["path"])
        content = params["content"]
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            existing = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            existing = path.read_text(encoding="latin-1")
        
        # Add newline if file doesn't end with one
        if existing and not existing.endswith("\n"):
            content = "\n" + content
        
        updated_content = existing + content
        
        try:
            path.write_text(updated_content, encoding="utf-8")
        except UnicodeEncodeError:
            path.write_text(updated_content, encoding="latin-1")
        
        output = f"Appended {len(content)} chars to {path}"
        return CapabilityResult.ok(output=output)

    def _insert_after_line(self, params: dict[str, Any]) -> CapabilityResult:
        """Insert content after the specified line number."""
        path = self._resolve(params["path"])
        line_number = params["line_number"]
        content = params["content"]
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            file_content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            file_content = path.read_text(encoding="latin-1")
        
        lines = file_content.splitlines()
        
        # If line_number exceeds file length, append to end
        if line_number >= len(lines):
            lines.append(content)
        else:
            lines.insert(line_number, content)
        
        updated_content = "\n".join(lines)
        
        try:
            path.write_text(updated_content, encoding="utf-8")
        except UnicodeEncodeError:
            path.write_text(updated_content, encoding="latin-1")
        
        output = f"Inserted content after line {line_number} in {path}"
        return CapabilityResult.ok(output=output)

    def _summarize_file(self, params: dict[str, Any]) -> CapabilityResult:
        """Return the first max_lines lines as a preview."""
        path = self._resolve(params["path"])
        max_lines = params.get("max_lines", 100)
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        
        lines = content.splitlines()
        preview_lines = lines[:max_lines]
        preview = "\n".join(preview_lines)
        
        header = f"File: {path.name}\nTotal lines: {len(lines)}\nSize: {len(content)} bytes\n"
        
        if len(lines) > max_lines:
            header += f"Showing first {max_lines} lines:\n\n"
        else:
            header += "\n"
        
        output = header + preview
        
        return CapabilityResult.ok(output=output)

    def _scan_project(self, params: dict[str, Any]) -> CapabilityResult:
        """Walk directory tree and collect matching files."""
        root = self._resolve(params["root"])
        extensions = params.get("extensions", [".py"])
        max_files = params.get("max_files", 50)
        exclude_dirs = params.get(
            "exclude_dirs",
            ["__pycache__", ".venv", "venv", "node_modules", ".git", "dist", "build", ".egg-info"]
        )
        
        if not root.exists():
            return CapabilityResult.fail(f"Directory not found: {root}")
        
        files_found = []
        
        for file_path in root.rglob("*"):
            if len(files_found) >= max_files:
                break
                
            # Skip directories and excluded paths
            if file_path.is_dir():
                continue
                
            # Check if any parent directory is excluded
            if any(exclude_dir in file_path.parts for exclude_dir in exclude_dirs):
                continue
            
            # Check file extension
            if file_path.suffix in extensions:
                try:
                    size = file_path.stat().st_size
                    line_count = 0
                    if file_path.suffix == ".py":
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            line_count = len(content.splitlines())
                        except UnicodeDecodeError:
                            pass
                    
                    relative_path = file_path.relative_to(root)
                    files_found.append({
                        "path": str(relative_path),
                        "size": size,
                        "lines": line_count
                    })
                except (OSError, UnicodeDecodeError):
                    continue
        
        # Build directory tree string
        output_parts = [f"Project scan: {root.name}"]
        output_parts.append(f"Extensions: {', '.join(extensions)}")
        output_parts.append(f"Files found: {len(files_found)}")
        output_parts.append("")
        
        for file_info in files_found:
            if file_info["lines"]:
                output_parts.append(f"  {file_info['path']} ({file_info['lines']} lines, {file_info['size']} bytes)")
            else:
                output_parts.append(f"  {file_info['path']} ({file_info['size']} bytes)")
        
        output = "\n".join(output_parts)
        
        metadata = {
            "root": str(root),
            "file_count": len(files_found),
            "extensions_scanned": extensions
        }
        
        return CapabilityResult.ok(output=output, metadata=metadata)

    def _check_contains(self, params: dict[str, Any]) -> CapabilityResult:
        """Return whether the file contains the search string."""
        path = self._resolve(params["path"])
        search = params["search"]
        
        if not path.exists():
            return CapabilityResult.fail(f"File not found: {path}")
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        
        found = search in content
        output = "found" if found else "not found"
        
        metadata = {
            "path": str(path),
            "search": search,
            "found": found
        }
        
        return CapabilityResult.ok(output=output, metadata=metadata)
