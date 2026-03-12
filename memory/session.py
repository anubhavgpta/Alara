"""Session memory management for the ALARA memory layer."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.orchestrator import OrchestratorResult
from memory.database import DatabaseManager
from memory.models import SessionEntry
from schemas.goal import GoalContext


class SessionMemory:
    """Manages the current execution session and persists results to SQLite."""
    
    def __init__(self) -> None:
        """Initialize session memory with a new session ID."""
        self.session_id = str(uuid.uuid4())
        self._current: dict[str, SessionEntry] = {}
        self.db = DatabaseManager.get_instance()
        logger.info("SessionMemory initialized with session_id: {}", self.session_id)
    
    def start_goal(self, goal: str, goal_context: GoalContext) -> str:
        """
        Create a new SessionEntry for a goal being executed.
        
        Args:
            goal: The goal string
            goal_context: The parsed goal context
            
        Returns:
            The entry ID
        """
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        entry = SessionEntry(
            id=entry_id,
            session_id=self.session_id,
            goal=goal,
            scope=goal_context.scope,
            status="running",
            steps_total=0,
            steps_completed=0,
            steps_failed=0,
            execution_log=[],
            key_outputs=[],
            created_at=now,
            completed_at=None,
        )
        
        # Store in memory
        self._current[entry_id] = entry
        
        # Persist to database
        self.db.execute(
            """
            INSERT INTO sessions (
                id, session_id, goal, scope, status, steps_total,
                steps_completed, steps_failed, execution_log, key_outputs, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id, entry.session_id, entry.goal, entry.scope, entry.status,
                entry.steps_total, entry.steps_completed, entry.steps_failed,
                json.dumps(entry.execution_log), json.dumps(entry.key_outputs),
                entry.created_at, entry.completed_at
            )
        )
        
        logger.debug("Started goal entry {} for goal: {}", entry_id, goal[:50])
        return entry_id
    
    def complete_goal(self, entry_id: str, result: OrchestratorResult, key_outputs: list[str] = None) -> None:
        """
        Update the entry when a goal completes.
        
        Args:
            entry_id: The entry ID to update
            result: The execution result
            key_outputs: Key outputs from AgentResult (optional)
        """
        if entry_id not in self._current:
            logger.warning("Attempted to complete unknown entry: {}", entry_id)
            return
        
        entry = self._current[entry_id]
        now = datetime.now(timezone.utc).isoformat()
        
        # Update status based on result
        if result.success:
            entry.status = "success"
        elif result.steps_completed > 0:
            entry.status = "partial"
        else:
            entry.status = "failed"
        
        entry.completed_at = now
        entry.steps_total = result.total_steps
        entry.steps_completed = result.steps_completed
        entry.steps_failed = result.steps_failed
        entry.execution_log = result.execution_log
        
        # Update key_outputs if provided
        if key_outputs is not None:
            entry.key_outputs = key_outputs
        
        # Update in memory
        self._current[entry_id] = entry
        
        # Persist to database
        self.db.execute(
            """
            UPDATE sessions SET
                status = ?, completed_at = ?, steps_total = ?,
                steps_completed = ?, steps_failed = ?, execution_log = ?, key_outputs = ?
            WHERE id = ?
            """,
            (
                entry.status, entry.completed_at, entry.steps_total,
                entry.steps_completed, entry.steps_failed,
                json.dumps(entry.execution_log), json.dumps(entry.key_outputs), entry_id
            )
        )
        
        logger.debug(
            "Completed goal entry {} with status: {} ({} steps)",
            entry_id, entry.status, entry.steps_completed
        )
    
    def get_recent(self, limit: int = 10) -> list[SessionEntry]:
        """
        Return the most recent session entries across all sessions.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of recent SessionEntry objects
        """
        results = self.db.execute(
            """
            SELECT * FROM sessions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        
        entries = []
        for row in results:
            # Deserialize execution_log and key_outputs from JSON
            execution_log = json.loads(row["execution_log"]) if row["execution_log"] else []
            key_outputs = json.loads(row["key_outputs"]) if row["key_outputs"] else []
            
            entry = SessionEntry(
                id=row["id"],
                session_id=row["session_id"],
                goal=row["goal"],
                scope=row["scope"],
                status=row["status"],
                steps_total=row["steps_total"],
                steps_completed=row["steps_completed"],
                steps_failed=row["steps_failed"],
                execution_log=execution_log,
                key_outputs=key_outputs,
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            entries.append(entry)
        
        return entries
    
    def get_current_session_entries(self) -> list[SessionEntry]:
        """
        Return all entries from the current session only.
        
        Returns:
            List of SessionEntry objects from current session
        """
        results = self.db.execute(
            """
            SELECT * FROM sessions
            WHERE session_id = ?
            ORDER BY created_at DESC
            """,
            (self.session_id,)
        )
        
        entries = []
        for row in results:
            # Deserialize execution_log and key_outputs from JSON
            execution_log = json.loads(row["execution_log"]) if row["execution_log"] else []
            key_outputs = json.loads(row["key_outputs"]) if row["key_outputs"] else []
            
            entry = SessionEntry(
                id=row["id"],
                session_id=row["session_id"],
                goal=row["goal"],
                scope=row["scope"],
                status=row["status"],
                steps_total=row["steps_total"],
                steps_completed=row["steps_completed"],
                steps_failed=row["steps_failed"],
                execution_log=execution_log,
                key_outputs=key_outputs,
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            entries.append(entry)
        
        return entries
    
    def get_entry(self, entry_id: str) -> SessionEntry | None:
        """
        Return a specific entry by ID.
        
        Args:
            entry_id: The entry ID to retrieve
            
        Returns:
            SessionEntry object or None if not found
        """
        # Check in-memory first
        if entry_id in self._current:
            return self._current[entry_id]
        
        # Check database
        results = self.db.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (entry_id,)
        )
        
        if not results:
            return None
        
        row = results[0]
        execution_log = json.loads(row["execution_log"]) if row["execution_log"] else []
        key_outputs = json.loads(row["key_outputs"]) if row["key_outputs"] else []
        
        return SessionEntry(
            id=row["id"],
            session_id=row["session_id"],
            goal=row["goal"],
            scope=row["scope"],
            status=row["status"],
            steps_total=row["steps_total"],
            steps_completed=row["steps_completed"],
            steps_failed=row["steps_failed"],
            execution_log=execution_log,
            key_outputs=key_outputs,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
    
    def search(self, query: str, limit: int = 5) -> list[SessionEntry]:
        """
        Search session history by goal text.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            List of matching SessionEntry objects
        """
        results = self.db.execute(
            """
            SELECT * FROM sessions
            WHERE goal LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", limit)
        )
        
        entries = []
        for row in results:
            execution_log = json.loads(row["execution_log"]) if row["execution_log"] else []
            key_outputs = json.loads(row["key_outputs"]) if row["key_outputs"] else []
            
            entry = SessionEntry(
                id=row["id"],
                session_id=row["session_id"],
                goal=row["goal"],
                scope=row["scope"],
                status=row["status"],
                steps_total=row["steps_total"],
                steps_completed=row["steps_completed"],
                steps_failed=row["steps_failed"],
                execution_log=execution_log,
                key_outputs=key_outputs,
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            entries.append(entry)
        
        return entries
    
    def get_stats(self) -> dict[str, Any]:
        """
        Return aggregate statistics for all sessions.
        
        Returns:
            Dictionary with session statistics
        """
        # Get total counts
        total_result = self.db.execute(
            "SELECT COUNT(*) as count FROM sessions"
        )[0]
        total_goals = total_result["count"]
        
        # Get status counts
        status_results = self.db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM sessions
            GROUP BY status
            """
        )
        
        status_counts = {row["status"]: row["count"] for row in status_results}
        successful_goals = status_counts.get("success", 0)
        failed_goals = status_counts.get("failed", 0)
        partial_goals = status_counts.get("partial", 0)
        
        # Calculate success rate
        success_rate = successful_goals / total_goals if total_goals > 0 else 0.0
        
        # Get most common scope
        scope_results = self.db.execute(
            """
            SELECT scope, COUNT(*) as count
            FROM sessions
            GROUP BY scope
            ORDER BY count DESC
            LIMIT 1
            """
        )
        most_common_scope = scope_results[0]["scope"] if scope_results else "none"
        
        return {
            "total_goals": total_goals,
            "successful_goals": successful_goals,
            "failed_goals": failed_goals,
            "partial_goals": partial_goals,
            "success_rate": success_rate,
            "most_common_scope": most_common_scope,
        }
    
    def get_context_history(self, limit: int = 5) -> list[dict]:
        """
        Return recent goals formatted for context resolution. Extracts paths from execution logs.
        
        Args:
            limit: Maximum number of recent entries to return
            
        Returns:
            List of dictionaries containing goal, output, and extracted paths
        """
        recent = self.get_recent(limit=limit)
        history = []
        for entry in recent:
            item = {
                'goal': entry.goal,
                'output': '',
                'paths': []
            }
            # Extract file paths from execution_log if present
            if hasattr(entry, 'execution_log') and entry.execution_log:
                try:
                    log = json.loads(entry.execution_log) if isinstance(entry.execution_log, str) else entry.execution_log
                    for step in (log or []):
                        params = step.get('params', {}) or {}
                        path = params.get('path')
                        if path:
                            item['paths'].append(path)
                        out = step.get('output', '')
                        if out:
                            item['output'] = out
                except Exception:
                    pass
            # Also extract from key_outputs
            if hasattr(entry, 'key_outputs') and entry.key_outputs:
                item['output'] = entry.key_outputs[0][:200]
            history.append(item)
        return history
