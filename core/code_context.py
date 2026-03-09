"""Code context builder for project awareness and structured code summaries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alara.capabilities.code import CodeCapability


class CodeContextBuilder:
    """Builds structured code context summaries for planner awareness."""

    def __init__(self) -> None:
        """Initialize with no dependencies - stateless and reusable."""
        self.code_capability = CodeCapability()

    def build(self, goal: str, working_dir: str = None, goal_scope: str = None) -> str:
        """Build a structured code context summary for the given goal."""
        try:
            # Only scan if goal scope is code-related
            if goal_scope not in ("cli", "mixed", "filesystem"):
                return ""
            
            # Infer project root
            project_root = self._infer_project_root(goal, working_dir)
            if not project_root or not project_root.exists():
                return ""
            
            # Scan project structure
            scan_result = self.code_capability.execute("scan_project", {
                "root": str(project_root),
                "extensions": [".py"],
                "max_files": 50
            })
            
            if not scan_result.success:
                return ""
            
            # Find key files
            key_files = self._find_key_files(goal, project_root, scan_result.metadata.get("file_count", 0))
            
            # Build context summary
            context_parts = [
                "=== CODE CONTEXT ===",
                f"Project root: {project_root}",
                "",
                "Project structure:",
                scan_result.output,
                ""
            ]
            
            if key_files:
                context_parts.append("Key files:")
                for file_path in key_files[:5]:  # Limit to 5 files
                    full_path = project_root / file_path
                    summary_result = self.code_capability.execute("summarize_file", {
                        "path": str(full_path),
                        "max_lines": 50
                    })
                    
                    if summary_result.success:
                        context_parts.append(f"\n{file_path}:")
                        context_parts.append(summary_result.output)
                
                context_parts.append("")
            
            context_parts.append("=== END CODE CONTEXT ===")
            
            return "\n".join(context_parts)
            
        except Exception:
            # Never raise - return empty string on any failure
            return ""

    def _infer_project_root(self, goal: str, working_dir: str = None) -> Path | None:
        """Attempt to find a relevant project directory."""
        # 1. If working_dir is provided and exists, use it
        if working_dir:
            working_path = Path(working_dir).expanduser().resolve()
            if working_path.exists() and working_path.is_dir():
                return working_path
        
        # 2. Scan goal for path-like strings in common directories
        home = Path.home()
        common_dirs = [home / "Desktop", home / "Documents", home / "Downloads"]
        
        # Extract potential folder names from goal
        goal_words = goal.lower().split()
        for word in goal_words:
            if len(word) > 2:  # Skip very short words
                for common_dir in common_dirs:
                    potential_dir = common_dir / word
                    if potential_dir.exists() and potential_dir.is_dir():
                        return potential_dir
        
        # 3. Try to find a project path mentioned in the goal by checking
        # if any known path alias points to a directory containing Python files
        # This would require access to memory manager, but for now we skip this
        # to avoid falling back to cwd
        
        # If nothing found, return None — do not fall back to cwd
        return None

    def _is_python_project(self, path: Path) -> bool:
        """Check if a directory looks like a Python project."""
        if not path.is_dir():
            return False
        
        # Look for Python project indicators
        indicators = [
            "pyproject.toml",
            "setup.py", 
            "requirements.txt",
            "Pipfile",
            "poetry.lock",
            ".python-version"
        ]
        
        for indicator in indicators:
            if (path / indicator).exists():
                return True
        
        # Look for Python files
        py_files = list(path.glob("*.py"))
        if py_files:
            return True
        
        return False

    def _find_key_files(self, goal: str, project_root: Path, file_count: int) -> list[Path]:
        """Find key files to include in the context."""
        key_files = []
        goal_lower = goal.lower()
        
        # 1. Files mentioned in the goal
        for file_path in project_root.rglob("*.py"):
            relative_path = file_path.relative_to(project_root)
            if file_path.name.lower() in goal_lower:
                key_files.append(relative_path)
        
        # 2. Main entry points at project root
        main_files = ["main.py", "app.py", "__init__.py"]
        for main_file in main_files:
            file_path = project_root / main_file
            if file_path.exists() and file_path not in key_files:
                key_files.append(file_path.name)
        
        # 3. Configuration files at project root
        config_files = ["requirements.txt", "pyproject.toml", ".env.example"]
        for config_file in config_files:
            file_path = project_root / config_file
            if file_path.exists() and file_path.name not in [f.name for f in key_files]:
                key_files.append(file_path.name)
        
        # 4. Other .py files in root (up to remaining budget)
        remaining_slots = 5 - len(key_files)
        if remaining_slots > 0:
            root_py_files = [f for f in project_root.glob("*.py") 
                           if f.name not in [f.name for f in key_files]]
            for py_file in root_py_files[:remaining_slots]:
                key_files.append(py_file.name)
        
        return [Path(f) for f in key_files]
