"""Skill memory management for the ALARA memory layer."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from alara.core.orchestrator import OrchestratorResult
from alara.memory.database import DatabaseManager
from alara.memory.models import SkillEntry
from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import TaskGraph


class SkillMemory:
    """Stores successful TaskGraphs as reusable templates for similar future goals."""
    
    SIMILARITY_THRESHOLD = 0.35
    
    def __init__(self) -> None:
        """Initialize skill memory."""
        self.db = DatabaseManager.get_instance()
        logger.info("SkillMemory initialized")
    
    def store(self, goal: str, goal_context: GoalContext, task_graph: TaskGraph,
              result: OrchestratorResult, duration_ms: float) -> SkillEntry | None:
        """
        Store a successful task as a skill template.
        
        Args:
            goal: The original goal string
            goal_context: The parsed goal context
            task_graph: The executed task graph
            result: The execution result
            duration_ms: Execution duration in milliseconds
            
        Returns:
            The created/updated SkillEntry or None if not stored
        """
        # Only store successful tasks with sufficient complexity
        if not result.success or result.steps_completed < 2:
            return None
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Generate skill name from goal (first 60 chars, cleaned)
        skill_name = re.sub(r'[^a-zA-Z0-9\s]', '', goal[:60]).strip()
        if len(skill_name) > 50:
            skill_name = skill_name[:47] + "..."
        
        # Extract tags
        tags = self._extract_tags(goal, goal_context.scope, goal_context.estimated_complexity)
        
        # Check for similar existing skill
        similar = self._find_similar(goal, threshold=0.8)
        if similar:
            # Update existing skill
            new_success_count = similar.success_count + 1
            new_avg_duration = (
                (similar.avg_duration_ms * similar.success_count + duration_ms) /
                new_success_count
            )
            
            self.db.execute(
                """
                UPDATE skills SET
                    success_count = ?, avg_duration_ms = ?, last_used_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_success_count, new_avg_duration, now, now, similar.id)
            )
            
            # Get updated entry
            updated = self.get(similar.id)
            logger.debug("Updated existing skill: {}", similar.name)
            return updated
        
        # Create new skill
        skill_id = str(uuid.uuid4())
        
        # Serialize steps as JSON
        serialized_steps = json.dumps([step.model_dump() for step in task_graph.steps])
        
        self.db.execute(
            """
            INSERT INTO skills (
                id, name, goal_pattern, scope, complexity, steps,
                success_count, failure_count, avg_duration_ms, tags,
                created_at, last_used_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill_id, skill_name, goal, goal_context.scope,
                goal_context.estimated_complexity, serialized_steps,
                1, 0, duration_ms, json.dumps(tags),
                now, now, now
            )
        )
        
        # Create and return skill entry
        skill = SkillEntry(
            id=skill_id,
            name=skill_name,
            goal_pattern=goal,
            scope=goal_context.scope,
            complexity=goal_context.estimated_complexity,
            steps=json.loads(serialized_steps),
            success_count=1,
            failure_count=0,
            avg_duration_ms=duration_ms,
            tags=tags,
            created_at=now,
            last_used_at=now,
            updated_at=now,
        )
        
        logger.debug("Created new skill: {}", skill_name)
        return skill
    
    def search(self, goal: str, limit: int = 3) -> list[SkillEntry]:
        """
        Find skills relevant to a goal using word overlap similarity.
        
        Args:
            goal: The goal string to search for
            limit: Maximum number of results to return
            
        Returns:
            List of relevant SkillEntry objects
        """
        # Get all skills
        results = self.db.execute("SELECT * FROM skills ORDER BY success_count DESC")
        
        if not results:
            return []
        
        # Tokenize the goal
        goal_tokens = self._tokenize_text(goal)
        
        scored_skills = []
        
        for row in results:
            skill_tokens = self._tokenize_text(row["goal_pattern"])
            
            # Calculate overlap similarity
            if not goal_tokens or not skill_tokens:
                overlap = 0.0
            else:
                overlap = len(goal_tokens & skill_tokens) / max(len(goal_tokens), len(skill_tokens))
            
            # Only consider skills above threshold
            if overlap >= self.SIMILARITY_THRESHOLD:
                # Calculate success rate
                success_rate = row["success_count"] / (row["success_count"] + row["failure_count"] + 1)
                
                # Calculate recency score
                last_used = row["last_used_at"]
                if last_used:
                    last_used_date = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
                    days_since_use = (datetime.now(timezone.utc) - last_used_date).days
                    if days_since_use <= 7:
                        recency_score = 1.0
                    elif days_since_use <= 30:
                        recency_score = 0.5
                    else:
                        recency_score = 0.0
                else:
                    recency_score = 0.0
                
                # Calculate final score
                final_score = (overlap * 0.6) + (success_rate * 0.3) + (recency_score * 0.1)
                
                scored_skills.append((final_score, row))
        
        # Sort by score and return top results
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        
        entries = []
        for score, row in scored_skills[:limit]:
            entry = SkillEntry(
                id=row["id"],
                name=row["name"],
                goal_pattern=row["goal_pattern"],
                scope=row["scope"],
                complexity=row["complexity"],
                steps=json.loads(row["steps"]),
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                avg_duration_ms=row["avg_duration_ms"],
                tags=json.loads(row["tags"]),
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
                updated_at=row["updated_at"],
            )
            entries.append(entry)
        
        logger.debug("Found {} relevant skills for goal: {}", len(entries), goal[:50])
        return entries
    
    def get(self, skill_id: str) -> SkillEntry | None:
        """
        Get a skill by ID.
        
        Args:
            skill_id: The skill ID to retrieve
            
        Returns:
            SkillEntry object or None if not found
        """
        result = self.db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        
        if not result:
            return None
        
        row = result[0]
        return SkillEntry(
            id=row["id"],
            name=row["name"],
            goal_pattern=row["goal_pattern"],
            scope=row["scope"],
            complexity=row["complexity"],
            steps=json.loads(row["steps"]),
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            avg_duration_ms=row["avg_duration_ms"],
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            updated_at=row["updated_at"],
        )
    
    def record_usage(self, skill_id: str, success: bool, duration_ms: float) -> None:
        """
        Update skill statistics after use.
        
        Args:
            skill_id: The skill ID that was used
            success: Whether the usage was successful
            duration_ms: Execution duration in milliseconds
        """
        try:
            # Get current skill data
            result = self.db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
            if not result:
                logger.warning("Attempted to record usage for unknown skill: {}", skill_id)
                return
            
            row = result[0]
            now = datetime.now(timezone.utc).isoformat()
            
            if success:
                new_success_count = row["success_count"] + 1
                new_failure_count = row["failure_count"]
                # Update rolling average duration
                new_avg_duration = (
                    (row["avg_duration_ms"] * row["success_count"] + duration_ms) /
                    new_success_count
                )
            else:
                new_success_count = row["success_count"]
                new_failure_count = row["failure_count"] + 1
                new_avg_duration = row["avg_duration_ms"]
            
            # Update skill
            self.db.execute(
                """
                UPDATE skills SET
                    success_count = ?, failure_count = ?, avg_duration_ms = ?,
                    last_used_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_success_count, new_failure_count, new_avg_duration,
                    now, now, skill_id
                )
            )
            
            logger.debug("Recorded usage for skill {}: success={}, duration={}ms",
                        skill_id, success, duration_ms)
            
        except Exception as e:
            logger.warning("Failed to record usage for skill {}: {}", skill_id, e)
    
    def _find_similar(self, goal: str, threshold: float = 0.8) -> SkillEntry | None:
        """
        Find a skill with very high similarity to the goal.
        
        Args:
            goal: The goal string to match
            threshold: Similarity threshold
            
        Returns:
            SkillEntry object or None if no match found
        """
        results = self.db.execute("SELECT * FROM skills")
        
        goal_tokens = self._tokenize_text(goal)
        
        for row in results:
            skill_tokens = self._tokenize_text(row["goal_pattern"])
            
            if not goal_tokens or not skill_tokens:
                overlap = 0.0
            else:
                overlap = len(goal_tokens & skill_tokens) / max(len(goal_tokens), len(skill_tokens))
            
            if overlap >= threshold:
                return SkillEntry(
                    id=row["id"],
                    name=row["name"],
                    goal_pattern=row["goal_pattern"],
                    scope=row["scope"],
                    complexity=row["complexity"],
                    steps=json.loads(row["steps"]),
                    success_count=row["success_count"],
                    failure_count=row["failure_count"],
                    avg_duration_ms=row["avg_duration_ms"],
                    tags=json.loads(row["tags"]),
                    created_at=row["created_at"],
                    last_used_at=row["last_used_at"],
                    updated_at=row["updated_at"],
                )
        
        return None
    
    def _tokenize_text(self, text: str) -> set[str]:
        """
        Tokenize text into meaningful words.
        
        Args:
            text: Text to tokenize
            
        Returns:
            Set of lowercase tokens
        """
        # Stop words to filter out
        stop_words = {
            'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or',
            'with', 'my', 'i', 'me', 'is', 'it', 'this', 'that', 'from', 'into',
            'inside', 'called', 'named'
        }
        
        # Split on whitespace and punctuation, convert to lowercase
        tokens = re.findall(r'\b\w+\b', text.lower())
        
        # Filter out stop words and short tokens
        return {token for token in tokens if token not in stop_words and len(token) > 2}
    
    def _extract_tags(self, goal: str, scope: str, complexity: str) -> list[str]:
        """
        Extract searchable tags from a goal.
        
        Args:
            goal: The goal string
            scope: Goal scope
            complexity: Goal complexity
            
        Returns:
            List of deduplicated lowercase tags
        """
        tags = set()
        
        # Add scope and complexity
        tags.add(scope.lower())
        tags.add(complexity.lower())
        
        # Extract action verbs
        action_verbs = {
            'create', 'install', 'delete', 'move', 'rename', 'find', 'run',
            'open', 'write', 'build', 'start', 'stop', 'update', 'download',
            'upload', 'copy', 'remove', 'add', 'set', 'get', 'list', 'show'
        }
        
        goal_lower = goal.lower()
        for verb in action_verbs:
            if verb in goal_lower:
                tags.add(verb)
        
        # Extract key nouns
        key_nouns = {
            'python', 'node', 'git', 'docker', 'fastapi', 'react', 'venv',
            'folder', 'file', 'project', 'app', 'server', 'database', 'api',
            'package', 'library', 'script', 'code', 'test', 'config'
        }
        
        for noun in key_nouns:
            if noun in goal_lower:
                tags.add(noun)
        
        return sorted(list(tags))
    
    def delete(self, skill_id: str) -> bool:
        """
        Delete a skill by ID.
        
        Args:
            skill_id: The skill ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        result = self.db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        deleted = result > 0
        if deleted:
            logger.debug("Deleted skill: {}", skill_id)
        return deleted
    
    def get_stats(self) -> dict[str, Any]:
        """
        Return skill statistics.
        
        Returns:
            Dictionary with skill statistics
        """
        # Get total skills
        total_result = self.db.execute("SELECT COUNT(*) as count FROM skills")[0]
        total_skills = total_result["count"]
        
        if total_skills == 0:
            return {
                "total_skills": 0,
                "most_used_skill": None,
                "avg_success_rate": 0.0,
                "total_executions": 0,
            }
        
        # Get most used skill
        most_used_result = self.db.execute(
            """
            SELECT name, success_count + failure_count as total_uses
            FROM skills
            ORDER BY total_uses DESC
            LIMIT 1
            """
        )
        most_used_skill = most_used_result[0]["name"] if most_used_result else None
        
        # Calculate average success rate
        skills = self.db.execute("SELECT success_count, failure_count FROM skills")
        total_success = sum(row["success_count"] for row in skills)
        total_executions = sum(row["success_count"] + row["failure_count"] for row in skills)
        avg_success_rate = total_success / total_executions if total_executions > 0 else 0.0
        
        return {
            "total_skills": total_skills,
            "most_used_skill": most_used_skill,
            "avg_success_rate": avg_success_rate,
            "total_executions": total_executions,
        }
