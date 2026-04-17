"""Background task queue backed by SQLite, executed in a thread pool."""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from alara.core.errors import AlaraError
from alara.tasks.models import BackgroundTask, TaskStatus

logger = logging.getLogger(__name__)

_CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    result      TEXT,
    error       TEXT,
    created_at  TEXT    NOT NULL,
    completed_at TEXT
)
"""

_SELECT_COLS = "id, description, status, result, error, created_at, completed_at"


def _row_to_task(row: tuple) -> BackgroundTask:
    task_id, description, status, result, error, created_at, completed_at = row
    return BackgroundTask(
        id=task_id,
        description=description,
        status=TaskStatus(status),
        result=result,
        error=error,
        created_at=datetime.fromisoformat(created_at),
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
    )


class TaskQueue:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=3)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(_CREATE_TASKS_TABLE)
            conn.commit()
        logger.debug("TaskQueue initialised — db=%s", db_path)

    def submit(self, description: str, session_id: int) -> BackgroundTask:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "INSERT INTO tasks (session_id, description, status, result, error, created_at, completed_at) "
                    "VALUES (?, ?, ?, NULL, NULL, ?, NULL)",
                    (session_id, description, TaskStatus.PENDING.value, now),
                )
                conn.commit()
                task_id: int = cursor.lastrowid  # type: ignore[assignment]
            finally:
                conn.close()

        task = BackgroundTask(
            id=task_id,
            description=description,
            status=TaskStatus.PENDING,
            result=None,
            error=None,
            created_at=datetime.fromisoformat(now),
            completed_at=None,
        )
        self._executor.submit(self._run_task, task_id, description)
        logger.debug("Task %d submitted: %s", task_id, description[:60])
        return task

    def _run_task(self, task_id: int, description: str) -> None:
        try:
            with self._lock:
                conn = sqlite3.connect(self._db_path)
                try:
                    conn.execute(
                        "UPDATE tasks SET status=? WHERE id=?",
                        (TaskStatus.RUNNING.value, task_id),
                    )
                    conn.commit()
                finally:
                    conn.close()

            import alara.capabilities.research as research_cap
            from alara.core.gemini import GeminiClient

            client = GeminiClient()
            result = research_cap.research(description, client)

            completed_at = datetime.now(timezone.utc).isoformat()
            with self._lock:
                conn = sqlite3.connect(self._db_path)
                try:
                    conn.execute(
                        "UPDATE tasks SET status=?, result=?, completed_at=? WHERE id=?",
                        (TaskStatus.DONE.value, result, completed_at, task_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            logger.debug("Task %d completed successfully", task_id)

        except Exception as exc:
            logger.exception("Task %d failed", task_id)
            completed_at = datetime.now(timezone.utc).isoformat()
            try:
                with self._lock:
                    conn = sqlite3.connect(self._db_path)
                    try:
                        conn.execute(
                            "UPDATE tasks SET status=?, error=?, completed_at=? WHERE id=?",
                            (TaskStatus.FAILED.value, str(exc), completed_at, task_id),
                        )
                        conn.commit()
                    finally:
                        conn.close()
            except Exception:
                logger.exception("Task %d: could not write FAILED status to database", task_id)

    def status(self, task_id: int) -> BackgroundTask:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            raise AlaraError(f"Task {task_id} not found")
        return _row_to_task(row)

    def list_all(self, session_id: int) -> list[BackgroundTask]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM tasks WHERE session_id=? ORDER BY id DESC",
                    (session_id,),
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_task(row) for row in rows]

    def cancel(self, task_id: int) -> bool:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT status FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                if row is None:
                    return False
                current = TaskStatus(row[0])
                if current == TaskStatus.PENDING:
                    conn.execute(
                        "UPDATE tasks SET status=? WHERE id=?",
                        (TaskStatus.CANCELLED.value, task_id),
                    )
                    conn.commit()
                    return True
                if current == TaskStatus.RUNNING:
                    logger.warning("Cannot cancel running task %d", task_id)
                return False
            finally:
                conn.close()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
        logger.debug("TaskQueue executor shut down")
