"""Persistent memory store — reads/writes to ~/.alara/alara.db."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".alara" / "alara.db"


def _get_conn() -> sqlite3.Connection:
    # Reuse the shared connection managed by alara.db (WAL already set there).
    from alara.db import _get_connection
    return _get_connection()


def save_memory(session_id: int, key: str, value: str, source: str = "auto") -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO memories (session_id, key, value, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(session_id, key) DO UPDATE SET
            value      = excluded.value,
            updated_at = datetime('now')
        """,
        (session_id, key, value, source),
    )
    conn.commit()
    logger.debug("Saved memory session=%d key=%r source=%s", session_id, key, source)


def get_all_memories() -> list[dict]:
    conn = _get_conn()
    cursor = conn.execute(
        "SELECT id, session_id, key, value, source, created_at FROM memories ORDER BY id"
    )
    return [
        {
            "id": row[0],
            "session_id": row[1],
            "key": row[2],
            "value": row[3],
            "source": row[4],
            "created_at": row[5],
        }
        for row in cursor.fetchall()
    ]


def forget_memory(memory_id: int) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    logger.debug("Deleted memory id=%d", memory_id)


def clear_all_memories() -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM memories")
    conn.execute("DELETE FROM session_summaries")
    conn.commit()
    logger.debug("Cleared all memories and session summaries")


def save_session_summary(session_id: int, summary: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO session_summaries (session_id, summary) VALUES (?, ?)",
        (session_id, summary),
    )
    conn.commit()
    logger.debug("Saved session summary session=%d", session_id)


def get_recent_summaries(n: int = 3) -> list[str]:
    conn = _get_conn()
    cursor = conn.execute(
        "SELECT summary FROM session_summaries ORDER BY created_at DESC LIMIT ?",
        (n,),
    )
    return [row[0] for row in cursor.fetchall()]
