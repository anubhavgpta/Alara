"""Decompose a user goal into a structured Plan via Gemini."""

from __future__ import annotations

import json
import logging
import uuid

from alara.agents.models import Plan, SubTask
from alara.agents.registry import valid_capability_names
from alara.core.errors import AlaraError
from alara.core.session import SessionContext
from alara.memory.extractor import _strip_fences

logger = logging.getLogger(__name__)


async def create_plan(goal: str, session: SessionContext) -> Plan:
    """Ask Gemini to decompose *goal* into a validated, cycle-free Plan."""
    plan_id = str(uuid.uuid4())
    names = ", ".join(valid_capability_names())
    system_prompt = (
        "You are a task planning assistant. Given a user goal, decompose it into "
        "subtasks as a JSON array. Each subtask must have: id (string, e.g. '1a'), "
        "description (string), capability (one of: "
        f"{names}"
        "), depends_on (list of subtask ids this step requires to complete first "
        "— empty list if none), is_destructive (bool). Return ONLY a JSON array "
        "with no markdown fences, no preamble."
    )

    full_prompt = f"{system_prompt}\n\nGoal: {goal}"
    try:
        response = session.gemini_client.chat(full_prompt, history=[])
        parsed: list[dict] = json.loads(_strip_fences(response))
    except json.JSONDecodeError as e:
        logger.warning("Plan parsing failed: %s", e)
        raise AlaraError("Plan parsing failed") from e
    except Exception as e:
        logger.warning("Plan parsing failed: %s", e)
        raise AlaraError("Plan parsing failed") from e

    valid_names = set(valid_capability_names())
    for item in parsed:
        cap = item.get("capability", "")
        if cap not in valid_names:
            raise AlaraError(f"Unknown capability: {cap}")

    steps = [SubTask(**s) for s in parsed]

    if _has_cycle(steps):
        raise AlaraError("Plan contains a dependency cycle")

    return Plan(id=plan_id, goal=goal, steps=steps)


def _has_cycle(steps: list[SubTask]) -> bool:
    """Return True if the dependency graph contains a cycle (Kahn's algorithm)."""
    in_degree: dict[str, int] = {s.id: 0 for s in steps}
    adjacency: dict[str, list[str]] = {s.id: [] for s in steps}

    for step in steps:
        for dep in step.depends_on:
            if dep in adjacency:
                adjacency[dep].append(step.id)
            in_degree[step.id] = in_degree.get(step.id, 0) + 1

    queue: list[str] = [sid for sid, deg in in_degree.items() if deg == 0]
    processed = 0

    while queue:
        node = queue.pop(0)
        processed += 1
        for neighbour in adjacency.get(node, []):
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    return processed < len(steps)
