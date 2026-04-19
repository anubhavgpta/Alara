from dataclasses import dataclass, field


@dataclass
class SubTask:
    id: str
    description: str
    capability: str
    depends_on: list[str]
    is_destructive: bool


@dataclass
class Plan:
    id: str
    goal: str
    steps: list[SubTask]
