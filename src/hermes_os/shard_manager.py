"""ShardManager — Physical user data sharding for Hermes OS.

Enables horizontal scaling by distributing user data across 100 physical
database shards at ~/.hermes/users/{shard:03d}/{user_id}.db.

This replaces the single-database model that cannot efficiently serve 100+ users.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import aiosqlite

logger = logging.getLogger(__name__)


class ShardManager:
    """Manages user data sharding across physical database files.

    Directory layout:
        ~/.hermes/users/{shard:03d}/{user_id}.db

    Example:
        ShardManager().db_path_for("user_abc123")
        # → Path("~/.hermes/users/042/user_abc123.db")
    """

    BASE_PATH = Path.home() / ".hermes" / "users"
    NUM_SHARDS = 100

    def __init__(self, num_shards: int = 100, base_path: Path | None = None) -> None:
        self.num_shards = num_shards
        if base_path is not None:
            self.BASE_PATH = base_path

    def shard_index_for(self, user_id: str) -> int:
        """Deterministic shard index for a user_id.

        Uses zlib.crc32 for deterministic hashing across all Python processes.
        Python's built-in hash() is randomized per-process for security.
        """
        import zlib
        return zlib.crc32(user_id.encode("utf-8")) % self.num_shards

    def db_path_for(self, user_id: str) -> Path:
        """Return the path to the user's sharded database file."""
        idx = self.shard_index_for(user_id)
        shard_dir = self.BASE_PATH / f"{idx:03d}"
        return shard_dir / f"{user_id}.db"

    def all_db_paths(self) -> list[Path]:
        """Return all existing shard DB paths (for migration/admin)."""
        paths: list[Path] = []
        if not self.BASE_PATH.exists():
            return paths
        for shard_dir in self.BASE_PATH.iterdir():
            # Skip non-shard dirs (e.g. _registry, _meta, etc.)
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)  # Must be numeric shard index
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix == ".db":
                    paths.append(db_file)
        return paths

    def get_stats(self) -> dict:
        """Return shard distribution statistics for monitoring.

        Returns:
            dict with keys:
            - total_users: total number of shard DBs
            - total_shards_used: number of shards that have at least one DB
            - shard_distribution: dict {shard_idx: user_count}
            - min_users_per_shard, max_users_per_shard, avg_users_per_shard
            - total_messages (across all sampled shards)
        """
        import sqlite3

        all_paths = self.all_db_paths()
        shard_users: dict[int, int] = {}
        total_messages = 0
        total_sessions = 0

        for db_path in all_paths:
            shard_idx = int(db_path.parent.name)
            shard_users[shard_idx] = shard_users.get(shard_idx, 0) + 1

            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.execute("SELECT COUNT(*) FROM messages")
                total_messages += cur.fetchone()[0]
                cur = conn.execute("SELECT COUNT(*) FROM sessions")
                total_sessions += cur.fetchone()[0]
                conn.close()
            except Exception:
                pass

        user_counts = list(shard_users.values()) if shard_users else [0]
        return {
            "total_users": len(all_paths),
            "total_shards_used": len(shard_users),
            "shard_distribution": shard_users,
            "min_users_per_shard": min(user_counts),
            "max_users_per_shard": max(user_counts),
            "avg_users_per_shard": sum(user_counts) / len(user_counts) if user_counts else 0.0,
            "total_messages": total_messages,
            "total_sessions": total_sessions,
        }


class ShardedStorage:
    """Storage wrapper that auto-routes reads/writes to the correct shard.

    Each user gets their own SQLite database file. Connections are cached
    per-shard to avoid repeated open/close overhead.
    """

    def __init__(self, shard_manager: ShardManager | None = None) -> None:
        self.shard_manager = shard_manager or ShardManager()
        self._connections: Dict[str, aiosqlite.Connection] = {}

    async def _get_db_for(self, user_id: str) -> aiosqlite.Connection:
        """Get or create a connection for the user's shard DB.

        Each user has their own DB file: ~/.hermes/users/{shard:03d}/{user_id}.db
        Connections are cached per user_id to avoid repeated open/close overhead.
        """
        if user_id not in self._connections:
            db_path = self.shard_manager.db_path_for(user_id)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = await aiosqlite.connect(str(db_path))
            conn.row_factory = aiosqlite.Row
            await self._apply_pragmas(conn)
            await self._lazy_initialize(conn, user_id)
            self._connections[user_id] = conn
            logger.debug("Opened shard DB at %s (user %s)", db_path, user_id)

        return self._connections[user_id]

    async def _apply_pragmas(self, db: aiosqlite.Connection) -> None:
        """Enforce WAL mode and normal synchronous for better concurrency."""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

    async def _lazy_initialize(self, db: aiosqlite.Connection, user_id: str) -> None:
        """Create shard-local tables. Idempotent — safe to call multiple times."""
        from datetime import UTC, datetime

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_shard_index (
                user_id TEXT PRIMARY KEY,
                shard_hint INTEGER DEFAULT 0,
                created_at TEXT,
                last_migrated_msg_id INTEGER DEFAULT 0
            )
        """)
        # Add last_migrated_msg_id to existing shard DBs created before this column existed
        try:
            await db.execute(
                "ALTER TABLE user_shard_index ADD COLUMN last_migrated_msg_id INTEGER DEFAULT 0"
            )
        except Exception:
            pass  # Column already exists
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES user_shard_index (user_id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp ON messages(user_id, timestamp)"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_states (
                user_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'IDLE',
                current_task_id TEXT,
                pending_decision TEXT,
                multi_step_progress REAL DEFAULT 0.0,
                last_updated TEXT,
                last_message_at TEXT,
                metadata TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'normal',
                depends_on TEXT DEFAULT '',
                result TEXT DEFAULT '',
                error TEXT DEFAULT '',
                progress REAL DEFAULT 0.0,
                created_at TEXT,
                updated_at TEXT,
                started_at TEXT DEFAULT '',
                completed_at TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        await db.commit()

    # -------------------------------------------------------------------------
    # Task storage (delegates to correct shard per user_id)
    # -------------------------------------------------------------------------

    async def create_task(self, task: "Task") -> None:
        """Create a task in the user's shard DB.

        Args:
            task: A Task object with task_id, user_id, title, etc.
        """
        conn = await self._get_db_for(task.user_id)
        await conn.execute(
            """
            INSERT INTO tasks
            (task_id, user_id, title, description, status, priority,
             depends_on, result, error, progress, created_at, updated_at,
             started_at, completed_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.user_id,
                task.title,
                task.description,
                task.status.value if hasattr(task.status, "value") else task.status,
                task.priority.value if hasattr(task.priority, "value") else task.priority,
                ",".join(task.depends_on) if task.depends_on else "",
                task.result or "",
                task.error or "",
                task.progress,
                task.created_at.isoformat() if task.created_at else "",
                task.updated_at.isoformat() if task.updated_at else "",
                task.started_at.isoformat() if task.started_at else "",
                task.completed_at.isoformat() if task.completed_at else "",
                str(task.metadata or {}),
            ),
        )
        await conn.commit()

    def _task_from_row(self, row: dict) -> "Task":
        """Reconstruct Task from a shard DB row dict."""
        from ast import literal_eval
        from datetime import datetime

        from hermes_os.task_scheduler import Task, TaskPriority, TaskStatus

        def _parse_dt(v: str | None) -> datetime | None:
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                return None

        depends_on = row.get("depends_on", "")
        depends_on = [d for d in depends_on.split(",") if d]

        metadata_str = row.get("metadata", "")
        try:
            metadata = literal_eval(metadata_str) if metadata_str else {}
        except Exception:
            metadata = {}

        status_str = row.get("status", "pending")
        priority_str = row.get("priority", "normal")

        return Task(
            task_id=row["task_id"],
            user_id=row["user_id"],
            title=row["title"],
            description=row.get("description", ""),
            status=TaskStatus(status_str) if status_str in [s.value for s in TaskStatus] else TaskStatus.PENDING,
            priority=TaskPriority(priority_str) if priority_str in [p.value for p in TaskPriority] else TaskPriority.NORMAL,
            depends_on=depends_on,
            result=row.get("result") or None,
            error=row.get("error") or None,
            progress=row.get("progress", 0.0),
            created_at=_parse_dt(row.get("created_at")) or datetime.now(_parse_utc()),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.now(_parse_utc()),
            started_at=_parse_dt(row.get("started_at")),
            completed_at=_parse_dt(row.get("completed_at")),
            metadata=metadata,
        )

    def _parse_utc(self):
        from datetime import UTC
        return UTC

    async def get_task(self, task_id: str) -> "Task | None":
        """Find a task by task_id across all shards (scans all shard DBs).

        For frequently-accessed tasks, consider caching task_id→shard mapping.
        """
        if not self.BASE_PATH.exists():
            return None
        for shard_dir in self.BASE_PATH.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix != ".db":
                    continue
                conn = await self._get_db_for(db_file.stem)
                async with conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        return self._task_from_row(dict(row))
        return None

    async def get_tasks_for_user(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list["Task"]:
        """Get tasks for a specific user from their shard DB."""
        conn = await self._get_db_for(user_id)
        if status:
            query = "SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?"
            args: tuple = (user_id, status, limit)
        else:
            query = "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            args = (user_id, limit)
        async with conn.execute(query, args) as cur:
            rows = await cur.fetchall()
        return [self._task_from_row(dict(row)) for row in rows]

    async def get_all_tasks(self) -> list["Task"]:
        """Get ALL tasks across all shard DBs."""
        all_tasks: list["Task"] = []
        if not self.BASE_PATH.exists():
            return all_tasks
        for shard_dir in self.BASE_PATH.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix != ".db":
                    continue
                conn = await self._get_db_for(db_file.stem)
                async with conn.execute("SELECT * FROM tasks ORDER BY created_at DESC") as cur:
                    rows = await cur.fetchall()
                for row in rows:
                    all_tasks.append(self._task_from_row(dict(row)))
        return all_tasks

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
        progress: float | None = None,
    ) -> None:
        """Update task status by task_id. Scans all shards to find the task."""
        from datetime import UTC, datetime

        if not self.BASE_PATH.exists():
            return
        for shard_dir in self.BASE_PATH.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix != ".db":
                    continue
                conn = await self._get_db_for(db_file.stem)
                # Check if task exists in this shard
                async with conn.execute(
                    "SELECT user_id FROM tasks WHERE task_id = ?", (task_id,)
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    continue
                # Found in this shard — update it
                now = datetime.now(UTC).isoformat()
                fields = ["status = ?", "updated_at = ?"]
                values: list = [status, now]
                if result is not None:
                    fields.append("result = ?")
                    values.append(result)
                if error is not None:
                    fields.append("error = ?")
                    values.append(error)
                if progress is not None:
                    fields.append("progress = ?")
                    values.append(progress)
                if status == "running":
                    fields.append("started_at = ?")
                    values.append(now)
                if status in ("completed", "failed"):
                    fields.append("completed_at = ?")
                    values.append(now)
                values.append(task_id)
                await conn.execute(
                    f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
                    values,
                )
                await conn.commit()
                return  # Done

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task by task_id. Returns True if deleted."""
        if not self.BASE_PATH.exists():
            return False
        for shard_dir in self.BASE_PATH.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix != ".db":
                    continue
                conn = await self._get_db_for(db_file.stem)
                cursor = await conn.execute(
                    "DELETE FROM tasks WHERE task_id = ?", (task_id,)
                )
                await conn.commit()
                if cursor.rowcount > 0:
                    return True
        return False

    async def get_runnable_tasks(self) -> list["Task"]:
        """Get all PENDING tasks whose dependencies are satisfied."""
        all_pending: list["Task"] = []
        if not self.BASE_PATH.exists():
            return all_pending
        for shard_dir in self.BASE_PATH.iterdir():
            if not shard_dir.is_dir():
                continue
            try:
                int(shard_dir.name)
            except ValueError:
                continue
            for db_file in shard_dir.iterdir():
                if db_file.suffix != ".db":
                    continue
                conn = await self._get_db_for(db_file.stem)
                async with conn.execute(
                    "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at DESC"
                ) as cur:
                    rows = await cur.fetchall()
                for row in rows:
                    all_pending.append(self._task_from_row(dict(row)))

        # Filter by dependency satisfaction
        runnable: list["Task"] = []
        for task in all_pending:
            if not task.depends_on:
                runnable.append(task)
                continue
            deps_met = True
            for dep_id in task.depends_on:
                dep = await self.get_task(dep_id)
                if dep is None or dep.status.value != "completed":
                    deps_met = False
                    break
            if deps_met:
                runnable.append(task)
        return runnable

    async def close(self) -> None:
        """Close all cached shard connections."""
        for user_id, conn in list(self._connections.items()):
            await conn.close()
            logger.debug("Closed shard DB for user %s", user_id)
        self._connections.clear()

    async def add_message(self, user_id: str, role: str, content: str) -> None:
        """Add a message and update last_message_at timestamp atomically."""
        from datetime import UTC, datetime

        conn = await self._get_db_for(user_id)
        now = datetime.now(UTC).isoformat()

        # Upsert conversation state with updated timestamp
        await conn.execute(
            """
            INSERT INTO messages (user_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, role, content, now),
        )

        # Update last_message_at in conversation_states
        await conn.execute(
            """
            INSERT INTO conversation_states (user_id, last_message_at, state)
            VALUES (?, ?, 'IDLE')
            ON CONFLICT(user_id) DO UPDATE SET
                last_message_at = excluded.last_message_at,
                state = COALESCE((SELECT state FROM conversation_states WHERE user_id = excluded.user_id), 'IDLE')
            """,
            (user_id, now),
        )
        await conn.commit()

    async def get_conversation_state(self, user_id: str) -> aiosqlite.Row | None:
        """Return the conversation state row for a user, or None if not found."""
        conn = await self._get_db_for(user_id)
        async with conn.execute(
            "SELECT * FROM conversation_states WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row

    async def migrate_from_single_db(self, single_db_path: Path) -> None:
        """Migrate all tables from a single-DB into per-user shard DBs.

        Maps tables:
        - users           → each user's own shard DB
        - messages        → each user's own shard DB (filtered by user_id)
        - sessions        → each user's own shard DB
        - conversation_states → each user's own shard DB

        Idempotent: safe to re-run. WAL mode enforced on all shard DBs.
        """
        import sqlite3
        from datetime import UTC, datetime

        src = sqlite3.connect(str(single_db_path))
        src.row_factory = sqlite3.Row

        # Detect which tables exist in the source DB
        cur = src.execute("SELECT name FROM sqlite_master WHERE type='table'")
        src_tables = {r[0] for r in cur.fetchall()}

        def rows(table: str) -> list[sqlite3.Row]:
            try:
                return src.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                return []

        users: dict[str, dict] = {}
        if "users" in src_tables:
            for row in rows("users"):
                users[row["user_id"]] = dict(row)

        # Migrate users and per-user tables
        for user_id, user_data in users.items():
            conn = await self._get_db_for(user_id)

            # Get last migrated message id BEFORE replacing user_shard_index
            last_migrated_id = 0
            async with conn.execute(
                "SELECT last_migrated_msg_id FROM user_shard_index WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    last_migrated_id = row[0] or 0

            # Migrate users table (preserve last_migrated_msg_id)
            if "users" in src_tables:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO user_shard_index
                        (user_id, created_at, last_migrated_msg_id)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, datetime.now(UTC).isoformat(), last_migrated_id),
                )

            max_migrated_id = last_migrated_id

            # Detect messages primary key column name (handles "id" vs "message_id" etc.)
            msg_pk_col = "id"
            try:
                cur = src.execute("PRAGMA table_info(messages)")
                for col in cur.fetchall():
                    # col format: (cid, name, type, notnull, dflt_value, pk)
                    if col[5] == 1:  # pk=1 means this column is the primary key
                        msg_pk_col = col[1]
                        break
            except Exception:
                pass

            # Migrate messages (incremental: only new ones)
            if "messages" in src_tables:
                msg_rows = src.execute(
                    f"SELECT * FROM messages WHERE user_id = ? AND {msg_pk_col} > ? ORDER BY {msg_pk_col}",
                    (user_id, last_migrated_id),
                ).fetchall()
                for row in msg_rows:
                    role = row["role"]
                    content = row["content"]
                    ts = row["timestamp"]
                    src_id = row[msg_pk_col]
                    await conn.execute(
                        """
                        INSERT INTO messages (user_id, role, content, timestamp)
                        VALUES (?, ?, ?, ?)
                        """,
                        (user_id, role, content, ts),
                    )
                    if src_id > max_migrated_id:
                        max_migrated_id = src_id

            # Update last migrated msg id
            if "messages" in src_tables and max_migrated_id > last_migrated_id:
                await conn.execute(
                    "UPDATE user_shard_index SET last_migrated_msg_id = ? WHERE user_id = ?",
                    (max_migrated_id, user_id),
                )

            # Migrate sessions
            if "sessions" in src_tables:
                sess_rows = src.execute(
                    "SELECT * FROM sessions WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
                for row in sess_rows:
                    session_id = row["session_id"]
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO sessions (user_id, session_id)
                        VALUES (?, ?)
                        """,
                        (user_id, session_id),
                    )

            # Migrate conversation_states
            if "conversation_states" in src_tables:
                state_rows = src.execute(
                    "SELECT * FROM conversation_states WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
                for row in state_rows:
                    await conn.execute(
                        """
                        INSERT OR REPLACE INTO conversation_states
                        (user_id, state, current_task_id, pending_decision,
                         multi_step_progress, last_updated, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            row["state"],
                            row.get("current_task_id", ""),
                            row.get("pending_decision", ""),
                            row.get("multi_step_progress", 0.0),
                            row.get("last_updated", ""),
                            row.get("metadata", "{}"),
                        ),
                    )

            await conn.commit()
            logger.info("Migrated user %s to shard DB", user_id)

        src.close()
        logger.info("Migration from %s complete", single_db_path)
