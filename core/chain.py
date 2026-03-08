"""Goal chaining context for multi-goal execution sessions."""

from __future__ import annotations

import re
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import List, Optional


@dataclass
class ChainEntry:
    """Represents a single completed goal in the chain."""
    goal: str
    status: str  # "success" | "partial" | "failed"
    steps_completed: int
    steps_total: int
    key_outputs: List[str]  # file paths, command outputs
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class ChainContext:
    """
    Accumulates results across chained goals
    within a single session.
    """
    
    def __init__(self):
        self.goals: List[ChainEntry] = []
        self.session_start = datetime.now(UTC)
    
    def add(self, goal: str, task_graph, execution_log: List, success: bool) -> None:
        """Record a completed goal."""
        if not task_graph:
            # Handle case where task_graph is None
            status = "failed" if not success else "success"
            steps_completed = 0
            steps_total = 0
        else:
            # Determine status based on success and completion
            if success:
                if task_graph.is_complete():
                    status = "success"
                else:
                    status = "partial"
            else:
                status = "failed"
            
            steps_completed = len([s for s in task_graph.steps if s.status.value == "done"])
            steps_total = len(task_graph.steps)
        
        # Extract key outputs from execution log
        key_outputs = self._extract_key_outputs(execution_log)
        
        entry = ChainEntry(
            goal=goal,
            status=status,
            steps_completed=steps_completed,
            steps_total=steps_total,
            key_outputs=key_outputs,
            timestamp=datetime.now(UTC)
        )
        
        self.goals.append(entry)
    
    def build_context_block(self) -> str:
        """
        Build a text block summarizing all
        previously completed goals in this chain.
        Used as additional context when planning
        the next goal.
        
        Format:
        
        === CHAIN CONTEXT ===
        Previous goals completed in this session:
        
        Goal 1: <goal text>
        Status: success/partial/failed
        Steps completed: N/M
        Key outputs:
          - <path or output from each successful step>
        
        Goal 2: ...
        === END CHAIN CONTEXT ===
        """
        if not self.goals:
            return ""
        
        lines = [
            "=== CHAIN CONTEXT ===",
            "Previous goals completed in this session:",
            ""
        ]
        
        for i, entry in enumerate(self.goals, 1):
            lines.append(f"Goal {i}: {entry.goal}")
            lines.append(f"Status: {entry.status}")
            lines.append(f"Steps completed: {entry.steps_completed}/{entry.steps_total}")
            
            if entry.key_outputs:
                lines.append("Key outputs:")
                for output in entry.key_outputs:
                    lines.append(f"  - {output}")
            
            lines.append("")  # Empty line between goals
        
        lines.append("=== END CHAIN CONTEXT ===")
        
        return "\n".join(lines)
    
    def summary(self) -> str:
        """
        One-line summary for display.
        e.g. "3 goals completed: 2 success, 1 partial"
        """
        if not self.goals:
            return "0 goals completed"
        
        total = len(self.goals)
        success = len([g for g in self.goals if g.status == "success"])
        partial = len([g for g in self.goals if g.status == "partial"])
        failed = len([g for g in self.goals if g.status == "failed"])
        
        parts = []
        if success:
            parts.append(f"{success} success")
        if partial:
            parts.append(f"{partial} partial")
        if failed:
            parts.append(f"{failed} failed")
        
        return f"{total} goals completed: {', '.join(parts)}"
    
    @property
    def is_empty(self) -> bool:
        return len(self.goals) == 0
    
    def _extract_key_outputs(self, execution_log: List) -> List[str]:
        """
        Extract key outputs from execution log.
        From execution_log, collect:
        - verification_detail values that start with
          "Path exists:" → extract the path
        - output values from successful steps that
          are not "(no output)" and are under 200 chars
        """
        outputs = []
        
        if not execution_log:
            return outputs
        
        for log_entry in execution_log:
            if not isinstance(log_entry, dict):
                continue
            
            # Extract from verification details
            verification_detail = log_entry.get("verification_detail", "")
            if verification_detail and isinstance(verification_detail, str):
                if verification_detail.startswith("Path exists:"):
                    path = verification_detail.replace("Path exists:", "").strip()
                    if path:
                        outputs.append(path)
            
            # Extract from step outputs
            output = log_entry.get("output", "")
            if output and isinstance(output, str):
                output = output.strip()
                # Include non-empty outputs that are not the default and are under 200 chars
                if (output and output != "(no output)" and len(output) <= 200 
                    and log_entry.get("success", False)):
                    outputs.append(output)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_outputs = []
        for output in outputs:
            if output not in seen:
                seen.add(output)
                unique_outputs.append(output)
        
        return unique_outputs


# Result object for _run_plan return value
PlanResult = namedtuple(
    "PlanResult",
    ["task_graph", "execution_log", "success"]
)
