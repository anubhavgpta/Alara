"""Database manager for the ALARA memory layer."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from loguru import logger


SCHEMA_VERSION = 2


class DatabaseManager:
    """Thread-safe singleton database manager for SQLite operations."""
    
    _instance: ClassVar[DatabaseManager | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    
    @classmethod
    def get_instance(cls) -> DatabaseManager:
        """Get the singleton DatabaseManager instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def __init__(self) -> None:
        """Initialize the database manager."""
        from utils.paths import get_db_path
        self._db_path = get_db_path()
        self._migrate_legacy_db()
        self._initialize()
        logger.info("DatabaseManager initialized with path: {}", self._db_path)
    
    def _migrate_legacy_db(self) -> None:
        """
        One-time migration: move alara.db from cwd
        to ~/.alara/alara.db if the new path is empty
        and the old path exists.
        """
        from pathlib import Path
        import shutil
        
        new_path = self._db_path
        old_path = Path.cwd() / "alara.db"

        if old_path.exists() and not new_path.exists():
            shutil.move(str(old_path), str(new_path))
            logger.info(
                f"Migrated alara.db from {old_path} to {new_path}"
            )
    
    def _initialize(self) -> None:
        """Create database and tables, run migrations if needed."""
        # Create parent directories if they don't exist
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = self._get_connection()
        try:
            # Enable WAL mode for concurrent reads
            conn.execute("PRAGMA journal_mode=WAL")
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys=ON")
            
            # Create schema version table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            
            # Get current schema version
            result = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current_version = result[0] if result else 0
            
            # Create tables
            self._create_tables(conn)
            
            # Run migrations if needed
            if current_version < SCHEMA_VERSION:
                self._run_migrations(conn, current_version)
            elif current_version == 0:
                # Fresh database - insert initial schema version
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat())
                )
            
            conn.commit()
            logger.info("Database initialized successfully")
        finally:
            conn.close()
    
    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """Create all database tables."""
        # Sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                steps_total INTEGER NOT NULL,
                steps_completed INTEGER NOT NULL,
                steps_failed INTEGER NOT NULL,
                execution_log TEXT NOT NULL,
                key_outputs TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        
        # Preferences table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                id TEXT PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'user_explicit',
                usage_count INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Skills table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                goal_pattern TEXT NOT NULL,
                scope TEXT NOT NULL,
                complexity TEXT NOT NULL,
                steps TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                avg_duration_ms REAL NOT NULL DEFAULT 0.0,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_skills_scope ON skills(scope)",
            "CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category)",
            "CREATE INDEX IF NOT EXISTS idx_preferences_key ON preferences(key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_preferences_category_key ON preferences(category, key)",
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
    
    def _run_migrations(self, conn: sqlite3.Connection, current_version: int) -> None:
        """Run database migrations from current_version to SCHEMA_VERSION."""
        logger.info("Running migrations from version {} to {}", current_version, SCHEMA_VERSION)
        
        if current_version < 2:
            # Add key_outputs column to sessions table
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN key_outputs TEXT NOT NULL DEFAULT '[]'")
                logger.info("Added key_outputs column to sessions table")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    logger.info("key_outputs column already exists")
                else:
                    raise
            
            # Update schema version to 2
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (2, datetime.now(timezone.utc).isoformat())
            )
        
        logger.info("Migrations completed successfully")
    
    def prune_old_sessions(self, keep_recent: int = 200) -> int:
        """
        Delete sessions older than the most recent
        keep_recent entries. Returns count deleted.

        Keeps the most recent 200 sessions in full.
        Anything older is deleted entirely.
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            DELETE FROM sessions
            WHERE id NOT IN (
                SELECT id FROM sessions
                ORDER BY created_at DESC
                LIMIT ?
            )
        """, (keep_recent,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        # VACUUM in a separate connection
        vacuum_conn = self._get_connection()
        vacuum_conn.execute("VACUUM")
        vacuum_conn.close()
        
        return deleted
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a new database connection with proper settings."""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=10,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode on each connection
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def execute(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a SQL query and return results as list of dicts."""
        conn = self._get_connection()
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                cursor = conn.execute(query, params)
                
                # Check if this is a write operation
                is_write = any(
                    query.strip().upper().startswith(prefix)
                    for prefix in ["INSERT", "UPDATE", "DELETE", "CREATE", "DROP"]
                )
                
                if is_write:
                    conn.commit()
                    results = []
                else:
                    results = [dict(row) for row in cursor.fetchall()]
                
                return results
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and retry_count < max_retries - 1:
                    retry_count += 1
                    time.sleep(0.1)  # 100ms backoff
                    continue
                else:
                    logger.error("Database error: {}", e)
                    raise
            except Exception as e:
                logger.error("Database error: {}", e)
                raise
            finally:
                conn.close()
        
        raise sqlite3.OperationalError("Max retries exceeded for database operation")
    
    def execute_many(self, query: str, params_list: list[tuple]) -> None:
        """Execute a SQL query with multiple parameter sets."""
        conn = self._get_connection()
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                conn.executemany(query, params_list)
                conn.commit()
                return
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and retry_count < max_retries - 1:
                    retry_count += 1
                    time.sleep(0.1)  # 100ms backoff
                    continue
                else:
                    logger.error("Database error: {}", e)
                    raise
            except Exception as e:
                logger.error("Database error: {}", e)
                raise
            finally:
                conn.close()
        
        raise sqlite3.OperationalError("Max retries exceeded for database operation")
    
    def health_check(self) -> dict[str, Any]:
        """Return database health status information."""
        try:
            # Get schema version
            version_result = self.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            schema_version = version_result[0]["version"] if version_result else 0
            
            # Get table counts
            session_count = self.execute("SELECT COUNT(*) as count FROM sessions")[0]["count"]
            preference_count = self.execute("SELECT COUNT(*) as count FROM preferences")[0]["count"]
            skill_count = self.execute("SELECT COUNT(*) as count FROM skills")[0]["count"]
            
            # Get database size
            db_size = self._db_path.stat().st_size if self._db_path.exists() else 0
            
            # Check WAL mode
            wal_mode_result = self.execute("PRAGMA journal_mode")
            wal_mode = wal_mode_result[0]["journal_mode"] == "wal" if wal_mode_result else False
            
            return {
                "status": "ok",
                "db_path": str(self._db_path),
                "schema_version": schema_version,
                "table_counts": {
                    "sessions": session_count,
                    "preferences": preference_count,
                    "skills": skill_count,
                },
                "db_size_bytes": db_size,
                "wal_mode": wal_mode,
            }
            
        except Exception as e:
            logger.error("Database health check failed: {}", e)
            return {
                "status": "error",
                "error": str(e),
                "db_path": str(self._db_path),
            }
