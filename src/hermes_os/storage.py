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
        return self._db

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
            """
            CREATE TABLE IF NOT EXISTS sessions (
                user_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )
            """
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
