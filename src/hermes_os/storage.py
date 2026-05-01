"""SQLite storage backend for Hermes OS."""

from __future__ import annotations

from typing import Any

import aiosqlite


class Storage:
    """Handles persistent storage for users and sessions.

    Uses lazy initialization: tables are created on first use.
    """

    def __init__(self, db_path: str = "hermes_os.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._apply_pragmas(self._db)
        return self._db

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def _lazy_initialize(self) -> None:
        """Create tables if they don't exist. Idempotent — safe to call multiple times."""
        db = await self._get_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                role TEXT,
                team TEXT,
                platform TEXT,
                platform_user_id TEXT,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp ON messages(user_id, timestamp)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                user_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_states (
                user_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'IDLE',
                current_task_id TEXT,
                pending_decision TEXT,
                multi_step_progress REAL DEFAULT 0.0,
                last_updated TEXT,
                metadata TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                status TEXT NOT NULL,
                output_artifact TEXT,
                error TEXT,
                duration_seconds REAL,
                total_stages INTEGER,
                completed_stages INTEGER,
                timestamp TEXT,
                pipeline_task_id TEXT,
                user_id TEXT,
                UNIQUE(task_id, stage_name)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_milestones_task ON pipeline_milestones(task_id, timestamp)"
        )
        await db.commit()

    async def initialize(self) -> None:
        """Public alias for _lazy_initialize for explicit initialization."""
        await self._lazy_initialize()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def save_user(self, user_dict: dict[str, Any]) -> None:
        await self._lazy_initialize()
        db = await self._get_db()
        await db.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, name, role, team, platform, platform_user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_dict["user_id"],
                user_dict["name"],
                user_dict["role"],
                user_dict["team"],
                user_dict["platform"],
                user_dict["platform_user_id"],
                (
                    user_dict["created_at"].isoformat()
                    if hasattr(user_dict["created_at"], "isoformat")
                    else str(user_dict["created_at"])
                ),
            ),
        )
        await db.commit()

    async def get_user_by_platform(
        self, platform: str, platform_user_id: str
    ) -> dict | None:
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM users WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_message(
        self, user_id: str, role: str, content: str, timestamp: str
    ) -> None:
        await self._lazy_initialize()
        db = await self._get_db()
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, timestamp),
        )
        await db.commit()

    async def get_messages(self, user_id: str, limit: int = 50) -> list[dict]:
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_messages(self, user_id: str) -> None:
        await self._lazy_initialize()
        db = await self._get_db()
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.commit()

    async def get_session_id(self, user_id: str) -> str | None:
        """Load persisted session_id for a user, or None if not yet created."""
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT session_id FROM sessions WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row["session_id"] if row else None

    async def save_session_id(self, user_id: str, session_id: str) -> None:
        """Persist a user's session_id. Idempotent via INSERT OR REPLACE."""
        await self._lazy_initialize()
        db = await self._get_db()
        await db.execute(
            "INSERT OR REPLACE INTO sessions (user_id, session_id) VALUES (?, ?)",
            (user_id, session_id),
        )
        await db.commit()

    async def delete_sessions_except(self, valid_user_ids: set[str]) -> None:
        """Delete all session records except those for the given user IDs."""
        await self._lazy_initialize()
        db = await self._get_db()
        if not valid_user_ids:
            await db.execute("DELETE FROM sessions")
        else:
            placeholders = ",".join(["?"] * len(valid_user_ids))
            await db.execute(
                f"DELETE FROM sessions WHERE user_id NOT IN ({placeholders})",
                list(valid_user_ids),
            )
        await db.commit()

    # -------------------------------------------------------------------------
    # Conversation State CRUD
    # -------------------------------------------------------------------------

    async def save_conversation_state(
        self,
        user_id: str,
        state: str,
        current_task_id: str | None = None,
        pending_decision: str | None = None,
        multi_step_progress: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        """Save or update a user's conversation state."""
        await self._lazy_initialize()
        db = await self._get_db()
        from datetime import UTC, datetime
        await db.execute(
            """
            INSERT OR REPLACE INTO conversation_states
            (user_id, state, current_task_id, pending_decision, multi_step_progress, last_updated, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                state,
                current_task_id,
                pending_decision,
                multi_step_progress,
                datetime.now(UTC).isoformat(),
                __import__("json").dumps(metadata) if metadata else None,
            ),
        )
        await db.commit()

    async def get_conversation_state(self, user_id: str) -> dict | None:
        """Load a user's conversation state, or None if not set."""
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM conversation_states WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def clear_conversation_state(self, user_id: str) -> None:
        """Reset a user's conversation state to IDLE."""
        await self._lazy_initialize()
        db = await self._get_db()
        await db.execute(
            "UPDATE conversation_states SET state = 'IDLE', current_task_id = NULL, pending_decision = NULL, multi_step_progress = 0.0 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()

    # -------------------------------------------------------------------------
    # Pipeline Milestone Persistence (Guardian Integration)
    # -------------------------------------------------------------------------

    async def save_milestone(
        self,
        task_id: str,
        stage_name: str,
        status: str,
        output_artifact: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
        total_stages: int = 0,
        completed_stages: int = 0,
        pipeline_task_id: str = "",
        user_id: str = "",
    ) -> None:
        """Persist a pipeline stage milestone to database."""
        await self._lazy_initialize()
        db = await self._get_db()
        from datetime import UTC, datetime
        timestamp = datetime.now(UTC).isoformat()
        await db.execute(
            """
            INSERT OR REPLACE INTO pipeline_milestones
            (task_id, stage_name, status, output_artifact, error, duration_seconds,
             total_stages, completed_stages, timestamp, pipeline_task_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                stage_name,
                status,
                output_artifact,
                error,
                duration_seconds,
                total_stages,
                completed_stages,
                timestamp,
                pipeline_task_id,
                user_id,
            ),
        )
        await db.commit()

    async def get_milestones(self, pipeline_task_id: str) -> list[dict]:
        """Get all milestones for a pipeline task, ordered by timestamp."""
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM pipeline_milestones WHERE pipeline_task_id = ? ORDER BY timestamp ASC",
            (pipeline_task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_latest_milestone(self, pipeline_task_id: str) -> dict | None:
        """Get the most recent milestone for a pipeline task."""
        await self._lazy_initialize()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT * FROM pipeline_milestones
            WHERE pipeline_task_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (pipeline_task_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
