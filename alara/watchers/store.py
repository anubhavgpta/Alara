"""SQLite reads/writes for the watcher subsystem."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from alara.watchers.models import Watcher, WatcherResult

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".alara" / "alara.db"


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(_DB_PATH), check_same_thread=False)


def save_watcher(
    description: str,
    schedule: str,
    tool: str | None,
    params: dict | None,
) -> int:
    """Insert a new watcher row and return its id."""
    conn = _conn()
    cursor = conn.execute(
        """
        INSERT INTO watchers (description, schedule, tool, params, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        (
            description,
            schedule,
            tool,
            json.dumps(params) if params else None,
        ),
    )
    conn.commit()
    conn.close()
    watcher_id: int = cursor.lastrowid  # type: ignore[assignment]
    logger.debug("Saved watcher id=%d description=%r", watcher_id, description)
    return watcher_id


def get_all_watchers(include_deleted: bool = False) -> list[Watcher]:
    """Return all watchers, optionally including deleted ones."""
    conn = _conn()
    if include_deleted:
        rows = conn.execute(
            "SELECT id, description, schedule, tool, params, last_run, last_result, status, created_at FROM watchers ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, description, schedule, tool, params, last_run, last_result, status, created_at FROM watchers WHERE status != 'deleted' ORDER BY id"
        ).fetchall()
    conn.close()
    return [
        Watcher(
            id=r[0],
            description=r[1],
            schedule=r[2],
            tool=r[3],
            params=json.loads(r[4]) if r[4] else None,
            last_run=r[5],
            last_result=r[6],
            status=r[7],
            created_at=r[8],
        )
        for r in rows
    ]


def get_watcher(watcher_id: int) -> Watcher | None:
    """Return a single watcher by id, or None if not found."""
    conn = _conn()
    row = conn.execute(
        "SELECT id, description, schedule, tool, params, last_run, last_result, status, created_at FROM watchers WHERE id = ?",
        (watcher_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return Watcher(
        id=row[0],
        description=row[1],
        schedule=row[2],
        tool=row[3],
        params=json.loads(row[4]) if row[4] else None,
        last_run=row[5],
        last_result=row[6],
        status=row[7],
        created_at=row[8],
    )


def update_watcher_run(watcher_id: int, result_summary: str) -> None:
    """Update last_run to now and store result_summary."""
    conn = _conn()
    conn.execute(
        "UPDATE watchers SET last_run = datetime('now'), last_result = ? WHERE id = ?",
        (result_summary[:500], watcher_id),
    )
    conn.commit()
    conn.close()


def delete_watcher(watcher_id: int) -> None:
    """Soft-delete a watcher by setting status to 'deleted'."""
    conn = _conn()
    conn.execute("UPDATE watchers SET status = 'deleted' WHERE id = ?", (watcher_id,))
    conn.commit()
    conn.close()


def pause_watcher(watcher_id: int) -> None:
    """Pause a watcher by setting status to 'paused'."""
    conn = _conn()
    conn.execute("UPDATE watchers SET status = 'paused' WHERE id = ?", (watcher_id,))
    conn.commit()
    conn.close()


def save_watcher_result(watcher_id: int, result: str, summary: str) -> None:
    """Insert a watcher_results row with surfaced=0."""
    conn = _conn()
    conn.execute(
        "INSERT INTO watcher_results (watcher_id, result, summary, surfaced) VALUES (?, ?, ?, 0)",
        (watcher_id, result, summary),
    )
    conn.commit()
    conn.close()


def get_unsurfaced_results() -> list[WatcherResult]:
    """Return all watcher results not yet shown in digest."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, watcher_id, result, summary, surfaced, created_at FROM watcher_results WHERE surfaced = 0 ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [
        WatcherResult(
            id=r[0],
            watcher_id=r[1],
            result=r[2],
            summary=r[3],
            surfaced=bool(r[4]),
            created_at=r[5],
        )
        for r in rows
    ]


def mark_results_surfaced(result_ids: list[int]) -> None:
    """Mark the given result IDs as surfaced."""
    if not result_ids:
        return
    conn = _conn()
    placeholders = ",".join("?" * len(result_ids))
    conn.execute(
        f"UPDATE watcher_results SET surfaced = 1 WHERE id IN ({placeholders})",
        result_ids,
    )
    conn.commit()
    conn.close()
