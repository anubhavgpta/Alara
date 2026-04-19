"""Dataclasses for the watcher subsystem."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Watcher:
    id: int
    description: str
    schedule: str
    tool: str | None
    params: dict | None
    last_run: str | None
    last_result: str | None
    status: str
    created_at: str


@dataclass
class WatcherResult:
    id: int
    watcher_id: int
    result: str
    summary: str
    surfaced: bool
    created_at: str
