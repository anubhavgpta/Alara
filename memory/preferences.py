"""Preference memory management for the ALARA memory layer."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from alara.memory.database import DatabaseManager
from alara.memory.models import PreferenceEntry
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import TaskGraph


class PreferenceMemory:
    """Persistent user preferences, path aliases, and inferred behaviors."""
    
    # Reserved Windows path segments that should never be stored as aliases
    RESERVED_PATH_SEGMENTS = {
        "users", "appdata", "windows", "program files", "program files (x86)",
        "programdata", "system32", "local", "roaming", "temp", "tmp",
    }
    
    def __init__(self) -> None:
        """Initialize preference memory."""
        self.db = DatabaseManager.get_instance()
        self._seed_defaults()
        self._fix_stale_file_aliases()
        logger.info("PreferenceMemory initialized")
    
    def _seed_defaults(self) -> None:
        """Insert default preferences if they don't exist."""
        defaults = [
            {
                "key": "python_venv_name",
                "value": "venv",
                "category": "tool",
                "source": "default",
                "confidence": 0.8,
            },
            {
                "key": "default_shell",
                "value": "powershell",
                "category": "tool",
                "source": "default",
                "confidence": 1.0,
            },
            {
                "key": "preferred_package_manager",
                "value": "pip",
                "category": "tool",
                "source": "default",
                "confidence": 0.9,
            },
        ]
        
        for pref in defaults:
            existing = self.db.execute(
                "SELECT id FROM preferences WHERE key = ?",
                (pref["key"],)
            )
            
            if not existing:
                now = datetime.now(timezone.utc).isoformat()
                self.db.execute(
                    """
                    INSERT INTO preferences (
                        id, key, value, category, confidence, source,
                        usage_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), pref["key"], json.dumps(pref["value"]),
                        pref["category"], pref["confidence"], pref["source"],
                        0, now, now
                    )
                )
                logger.debug("Seeded default preference: {}", pref["key"])
    
    def set(self, key: str, value: Any, category: str = "general",
            source: str = "user_explicit", confidence: float = 1.0) -> PreferenceEntry:
        """
        Upsert a preference.
        
        Args:
            key: Preference key
            value: Preference value (will be JSON serialized)
            category: Preference category
            source: Source of the preference
            confidence: Confidence level (0.0 to 1.0)
            
        Returns:
            The resulting PreferenceEntry
        """
        now = datetime.now(timezone.utc).isoformat()
        serialized_value = json.dumps(value)
        
        # Check if key exists
        existing = self.db.execute(
            "SELECT * FROM preferences WHERE key = ?",
            (key,)
        )
        
        if existing:
            # Update existing
            row = existing[0]
            new_usage_count = row["usage_count"] + 1
            
            self.db.execute(
                """
                UPDATE preferences SET
                    value = ?, confidence = ?, updated_at = ?, usage_count = ?
                WHERE key = ?
                """,
                (serialized_value, confidence, now, new_usage_count, key)
            )
            
            entry = PreferenceEntry(
                id=row["id"],
                key=row["key"],
                value=serialized_value,
                category=row["category"],
                confidence=confidence,
                source=row["source"],
                usage_count=new_usage_count,
                last_used_at=row["last_used_at"],
                created_at=row["created_at"],
                updated_at=now,
            )
            logger.debug("Updated preference: {}", key)
        else:
            # Insert new
            entry_id = str(uuid.uuid4())
            self.db.execute(
                """
                INSERT INTO preferences (
                    id, key, value, category, confidence, source,
                    usage_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id, key, serialized_value, category, confidence,
                    source, 1, now, now
                )
            )
            
            entry = PreferenceEntry(
                id=entry_id,
                key=key,
                value=serialized_value,
                category=category,
                confidence=confidence,
                source=source,
                usage_count=1,
                last_used_at=None,
                created_at=now,
                updated_at=now,
            )
            logger.debug("Created new preference: {}", key)
        
        return entry
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a preference value by key.
        
        Args:
            key: Preference key
            default: Default value if not found
            
        Returns:
            Deserialized preference value or default
        """
        try:
            result = self.db.execute(
                "SELECT * FROM preferences WHERE key = ?",
                (key,)
            )
            
            if not result:
                return default
            
            row = result[0]
            
            # Update usage count and last_used_at
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                """
                UPDATE preferences SET
                    usage_count = usage_count + 1, last_used_at = ?
                WHERE key = ?
                """,
                (now, key)
            )
            
            # Deserialize and return value
            return json.loads(row["value"])
            
        except Exception as e:
            logger.warning("Failed to get preference {}: {}", key, e)
            return default
    
    def get_entry(self, key: str) -> PreferenceEntry | None:
        """
        Get the full PreferenceEntry including metadata.
        
        Args:
            key: Preference key
            
        Returns:
            PreferenceEntry object or None if not found
        """
        result = self.db.execute(
            "SELECT * FROM preferences WHERE key = ?",
            (key,)
        )
        
        if not result:
            return None
        
        row = result[0]
        return PreferenceEntry(
            id=row["id"],
            key=row["key"],
            value=row["value"],
            category=row["category"],
            confidence=row["confidence"],
            source=row["source"],
            usage_count=row["usage_count"],
            last_used_at=row["last_used_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    
    def get_by_category(self, category: str) -> list[PreferenceEntry]:
        """
        Get all preferences in a category.
        
        Args:
            category: Preference category
            
        Returns:
            List of PreferenceEntry objects
        """
        results = self.db.execute(
            "SELECT * FROM preferences WHERE category = ? ORDER BY usage_count DESC",
            (category,)
        )
        
        entries = []
        for row in results:
            entry = PreferenceEntry(
                id=row["id"],
                key=row["key"],
                value=row["value"],
                category=row["category"],
                confidence=row["confidence"],
                source=row["source"],
                usage_count=row["usage_count"],
                last_used_at=row["last_used_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            entries.append(entry)
        
        return entries
    
    def set_path_alias(self, alias: str, absolute_path: str) -> PreferenceEntry:
        """
        Convenience method for storing path aliases.
        
        Args:
            alias: Path alias name
            absolute_path: Absolute path
            
        Returns:
            The created/updated PreferenceEntry
        """
        normalized_path = Path(absolute_path).as_posix()
        return self.set(alias, normalized_path, category="path")
    
    def get_path_alias(self, alias: str) -> str | None:
        """
        Resolves a path alias to its absolute path.
        
        Args:
            alias: Path alias name
            
        Returns:
            Absolute path or None if not found
        """
        # Try exact match first
        result = self.get(alias)
        if result is not None:
            return str(result)
        
        # Try case-insensitive match
        results = self.db.execute(
            "SELECT * FROM preferences WHERE category = 'path' AND key LIKE ?",
            (alias,)
        )
        
        if results:
            return json.loads(results[0]["value"])
        
        return None
    
    def get_all_path_aliases(self) -> dict[str, str]:
        """
        Returns all path aliases as {alias: absolute_path} dict.
        
        Returns:
            Dictionary mapping aliases to absolute paths
        """
        results = self.db.execute(
            "SELECT key, value FROM preferences WHERE category = 'path'"
        )
        
        aliases = {}
        for row in results:
            aliases[row["key"]] = json.loads(row["value"])
        
        return aliases
    
    def infer_from_execution(self, goal: str, task_graph: TaskGraph,
                              result) -> None:
        """
        Automatically infer preferences from a successful execution.
        
        Args:
            goal: The original goal string
            task_graph: The executed task graph
            result: The execution result
        """
        if not result.success:
            return
        
        try:
            # Extract path aliases
            self._infer_path_aliases(goal, task_graph)
            
            # Extract tool preferences
            self._infer_tool_preferences(task_graph)
            
            # Extract package patterns
            self._infer_package_patterns(task_graph)
            
            logger.debug("Completed preference inference from execution")
            
        except Exception as e:
            logger.warning("Preference inference failed: {}", e)
    
    def _infer_path_aliases(self, goal: str, task_graph: TaskGraph) -> None:
        """Extract path aliases from goal and execution."""
        # Simple heuristic: look for folder names in goal that match paths in steps
        goal_words = re.findall(r'\b\w+\b', goal.lower())
        
        for step in task_graph.steps:
            if step.step_type.value == "filesystem":
                for param_value in step.params.values():
                    if isinstance(param_value, str) and Path(param_value).is_absolute():
                        # Apply normalization to get directory path instead of file path
                        raw_path = param_value
                        p = Path(raw_path)
                        
                        # If the path points to a file, use the parent directory instead
                        if p.suffix:
                            normalized_path = str(p.parent).replace("\\", "/")
                        else:
                            normalized_path = str(p).replace("\\", "/")
                        
                        # Check if any goal word matches part of this path
                        path_parts = Path(normalized_path).parts
                        for word in goal_words:
                            if len(word) > 3 and word in [p.lower() for p in path_parts]:
                                # Store as alias using best matching path segment
                                alias = f"{word} folder"
                                best_path = self._best_alias_path(word, Path(raw_path))
                                
                                # Additional check: ensure the best path doesn't point directly to reserved segments
                                best_path_parts = Path(best_path).parts
                                if len(best_path_parts) > 0 and best_path_parts[-1].lower() in self.RESERVED_PATH_SEGMENTS:
                                    logger.debug(f"Skipping alias '{alias}' -> '{best_path}' because it points to reserved segment")
                                    continue
                                
                                existing = self.get_path_alias(alias)
                                if existing is None or existing != best_path:
                                    self.set_path_alias(alias, best_path)
                                    logger.debug("Inferred path alias: {} -> {}", alias, best_path)
    
    def _best_alias_path(self, noun: str, full_path: Path) -> str:
        """
        Given a noun like 'documents' and a full path
        like .../Documents/testapi/main.py, return
        the most relevant directory segment.
        
        Rules in order:
        1. If noun matches full_path.name (case
           insensitive), return str(full_path.parent)
           if it's a file, else str(full_path)
        2. Walk the path parts and find the part
           that most closely matches the noun.
           Skip reserved Windows segments.
           Return the path up to and including that
           part.
        3. If no part matches, return the parent
           directory of the full path.
        """
        noun_lower = noun.lower().strip()
        parts = full_path.parts
        
        # Check each path segment, skipping reserved ones
        for i, part in enumerate(parts):
            if noun_lower in part.lower():
                # Check if this segment is reserved
                if part.lower() in self.RESERVED_PATH_SEGMENTS:
                    continue  # Skip reserved segments
                
                # Return path up to this segment
                matched = Path(*parts[:i+1])
                return str(matched).replace("\\", "/")
        
        # No match — fall back to parent if file,
        # or path itself if directory
        if full_path.suffix:
            return str(full_path.parent).replace("\\", "/")
        return str(full_path).replace("\\", "/")
    
    def _infer_tool_preferences(self, task_graph: TaskGraph) -> None:
        """Extract tool preferences from CLI steps."""
        tools_seen = set()
        
        for step in task_graph.steps:
            if step.step_type.value == "cli" and "command" in step.params:
                command = step.params["command"]
                if isinstance(command, str):
                    # Extract tool names from commands
                    if command.startswith(("pip ", "pip3 ")):
                        tools_seen.add("pip")
                    elif command.startswith(("npm ", "yarn ")):
                        tools_seen.add("node")
                    elif command.startswith(("git ")):
                        tools_seen.add("git")
                    elif command.startswith(("docker ")):
                        tools_seen.add("docker")
        
        # Store tool preferences
        for tool in tools_seen:
            key = f"preferred_{tool}"
            existing = self.get(key)
            if existing is None:
                self.set(key, tool, category="tool", source="inferred", confidence=0.7)
                logger.debug("Inferred tool preference: {} = {}", key, tool)
    
    def _infer_package_patterns(self, task_graph: TaskGraph) -> None:
        """Extract commonly used packages from pip install commands."""
        packages = set()
        
        for step in task_graph.steps:
            if step.step_type.value == "cli" and "command" in step.params:
                command = step.params["command"]
                if isinstance(command, str) and command.startswith("pip install"):
                    # Extract package names
                    parts = command.split()
                    if len(parts) >= 3:
                        for part in parts[2:]:
                            if part and not part.startswith("-"):
                                packages.add(part)
        
        if packages:
            key = "common_packages"
            existing_packages = self.get(key, [])
            if isinstance(existing_packages, list):
                # Merge with existing packages
                merged_packages = list(set(existing_packages + list(packages)))
                self.set(key, merged_packages, category="package", source="inferred", confidence=0.6)
                logger.debug("Inferred common packages: {}", packages)
    
    def delete(self, key: str) -> bool:
        """
        Delete a preference by key.
        
        Args:
            key: Preference key to delete
            
        Returns:
            True if deleted, False if not found
        """
        result = self.db.execute("DELETE FROM preferences WHERE key = ?", (key,))
        deleted = len(result) > 0 if isinstance(result, list) else result > 0
        if deleted:
            logger.debug("Deleted preference: {}", key)
        return deleted
    
    def export(self) -> dict[str, Any]:
        """
        Export all preferences as a serializable dict.
        
        Returns:
            Dictionary containing all preferences
        """
        results = self.db.execute("SELECT * FROM preferences ORDER BY category, key")
        
        export_data = {}
        for row in results:
            try:
                value = json.loads(row["value"])
                export_data[row["key"]] = {
                    "value": value,
                    "category": row["category"],
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "usage_count": row["usage_count"],
                    "last_used_at": row["last_used_at"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            except json.JSONDecodeError:
                logger.warning("Failed to deserialize preference value for key: {}", row["key"])
        
        return export_data
    
    def _fix_stale_file_aliases(self) -> None:
        """
        One-time cleanup: find any stored path aliases
        whose value points to a file (has a suffix like
        .py, .txt, .md, .json etc) and replace the
        value with the parent directory.
        
        Also removes aliases pointing to reserved Windows
        path segments.
        
        This repairs aliases stored before the
        _best_alias_path fix was applied.
        """
        from pathlib import Path
        
        aliases = self.get_all_path_aliases()
        for noun, path_str in aliases.items():
            p = Path(path_str)
            path_parts = p.parts  # Define path_parts here for both cases
            
            # Fix 1: Replace file paths with parent directory
            if p.suffix:  # it's a file path
                fixed = str(p.parent).replace("\\", "/")
                # Use the internal set method to update
                self.set(noun, fixed)
                logger.debug(
                    f"Fixed stale file alias: "
                    f"{noun} -> {path_str} => {fixed}"
                )
            else:
                # Fix 2: Remove aliases pointing to reserved segments
                # Only block if the FINAL segment is reserved (not parent directories)
                if len(path_parts) > 0 and path_parts[-1].lower() in self.RESERVED_PATH_SEGMENTS:
                    # Delete the problematic alias
                    self.delete(noun)
                    logger.debug(
                        f"Removed reserved segment alias: "
                        f"{noun} -> {path_str}"
                    )
