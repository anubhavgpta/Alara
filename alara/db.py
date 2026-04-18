"""SQLite database layer for Alara session and message persistence."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".alara" / "alara.db"
_connection: sqlite3.Connection | None = None


_SESSIONS_REQUIRED = {"id", "started_at", "ended_at"}
_MESSAGES_REQUIRED = {"id", "session_id", "role", "content", "ts"}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for *table*."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _schema_is_valid(conn: sqlite3.Connection) -> bool:
    """Return True if both tables exist with exactly the required columns."""
    sessions_cols = _column_names(conn, "sessions")
    messages_cols = _column_names(conn, "messages")
    return (
        _SESSIONS_REQUIRED.issubset(sessions_cols)
        and not (sessions_cols - _SESSIONS_REQUIRED)
        and _MESSAGES_REQUIRED.issubset(messages_cols)
        and not (messages_cols - _MESSAGES_REQUIRED)
    )


def _reset_schema(conn: sqlite3.Connection) -> None:
    """Drop and recreate both tables, discarding any incompatible existing data."""
    logger.warning(
        "Incompatible database schema detected — dropping and recreating tables. "
        "Session history will be cleared."
    )
    conn.execute("DROP TABLE IF EXISTS messages")
    conn.execute("DROP TABLE IF EXISTS sessions")
    conn.execute("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            ended_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            role TEXT,
            content TEXT,
            ts TEXT
        )
    """)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is not None:
        return _connection

    db_dir = _DB_PATH.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Opening database at %s", _DB_PATH)

    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    logger.debug("WAL mode enabled")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            ended_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            role TEXT,
            content TEXT,
            ts TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES sessions(id),
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            source     TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(session_id, key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES sessions(id),
            summary    TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    if not _schema_is_valid(conn):
        _reset_schema(conn)

    logger.debug("Schema initialised")

    _connection = conn
    return _connection


def create_session() -> int:
    """Insert a new session row and return its id."""
    conn = _get_connection()
    started_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO sessions (started_at) VALUES (?)", (started_at,)
    )
    conn.commit()
    session_id = cursor.lastrowid
    logger.debug("Created session %d", session_id)
    return session_id


def end_session(session_id: int) -> None:
    """Mark a session as ended."""
    conn = _get_connection()
    ended_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ?", (ended_at, session_id)
    )
    conn.commit()
    logger.debug("Ended session %d", session_id)


def save_message(session_id: int, role: str, content: str) -> None:
    """Persist a message (user or assistant) to the database."""
    conn = _get_connection()
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (session_id, role, content, ts),
    )
    conn.commit()
    logger.debug("Saved message role=%s session=%d", role, session_id)


def get_session_messages(session_id: int) -> list[dict]:
    """Return all messages for a given session, ordered by id."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT role, content, ts FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    )
    return [{"role": row[0], "content": row[1], "ts": row[2]} for row in cursor.fetchall()]
