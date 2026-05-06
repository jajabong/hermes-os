"""Tests for user migration: single DB → 100 shards."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Tests: ShardManager with existing single DB
# ---------------------------------------------------------------------------


def test_shard_manager_existing_db_paths(tmp_path: Path) -> None:
    """all_db_paths() should return paths for all existing shard DBs."""
    from hermes_os.shard_manager import ShardManager

    # Create fake shard dirs
    sm = ShardManager(base_path=tmp_path, num_shards=100)
    shard_dir = tmp_path / "042"
    shard_dir.mkdir(parents=True)
    user_db = shard_dir / "user_abc123.db"
    user_db.touch()

    paths = sm.all_db_paths()
    assert user_db in paths


def test_shard_manager_single_db_not_in_shard_structure(tmp_path: Path) -> None:
    """Single DB files (hermes_os.db) should NOT be treated as shard DBs."""
    from hermes_os.shard_manager import ShardManager

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    # Create a top-level single DB (not in shard structure)
    single_db = tmp_path / "hermes_os.db"
    single_db.touch()

    paths = sm.all_db_paths()
    assert single_db not in paths  # Not in shard dir structure


# ---------------------------------------------------------------------------
# Tests: migration schema mapping
# ---------------------------------------------------------------------------


def test_single_db_has_expected_tables() -> None:
    """hermes_os.db should have: users, messages, sessions, conversation_states, pipeline_milestones."""
    # These tests verify the source DB schema — they read from the actual DB path.
    # When the source DB doesn't exist at the expected path (e.g., after migration
    # to shards), these tests skip. They are not testing migration logic.
    src_path = Path("hermes_os.db")
    if not src_path.exists():
        pytest.skip("hermes_os.db not present (may have been migrated)")

    conn = sqlite3.connect(str(src_path))
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()

    expected = {"users", "messages", "sessions", "conversation_states", "pipeline_milestones"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_single_db_users_table_schema() -> None:
    """users table should have user_id, name, platform, team columns."""
    src_path = Path("hermes_os.db")
    if not src_path.exists():
        pytest.skip("hermes_os.db not present")

    conn = sqlite3.connect(str(src_path))
    cur = conn.execute("PRAGMA table_info(users)")
    cols = {r[1] for r in cur.fetchall()}
    conn.close()

    assert "user_id" in cols
    assert "name" in cols
    assert "platform" in cols
    assert "team" in cols


def test_single_db_messages_table_schema() -> None:
    """messages table should have user_id, role, content, timestamp columns."""
    src_path = Path("hermes_os.db")
    if not src_path.exists():
        pytest.skip("hermes_os.db not present")

    conn = sqlite3.connect(str(src_path))
    cur = conn.execute("PRAGMA table_info(messages)")
    cols = {r[1] for r in cur.fetchall()}
    conn.close()

    assert "user_id" in cols
    assert "role" in cols
    assert "content" in cols
    assert "timestamp" in cols


# ---------------------------------------------------------------------------
# Tests: MigrationRunner
# ---------------------------------------------------------------------------


def test_migration_runner_migrates_users_table(tmp_path: Path) -> None:
    """Migrate users from single DB to sharded DBs."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    # Create source single DB
    src_db = tmp_path / "hermes_os.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            platform TEXT,
            team TEXT DEFAULT 'default'
        )
    """)
    conn.execute("INSERT INTO users VALUES ('u1', 'Alice', 'feishu', 'default')")
    conn.execute("INSERT INTO users VALUES ('u2', 'Bob', 'feishu', 'default')")
    conn.commit()
    conn.close()

    # Migrate
    sm = ShardManager(base_path=tmp_path / "users", num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    asyncio.run(storage.migrate_from_single_db(src_db))

    # Verify users are now in correct shards
    u1_shard = sm.shard_index_for("u1")
    u1_path = tmp_path / "users" / f"{u1_shard:03d}" / "u1.db"
    assert u1_path.exists(), f"u1 should be in shard {u1_shard} at {u1_path}"

    conn2 = sqlite3.connect(str(u1_path))
    cur = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn2.close()
    # Migrated shard DB has: user_shard_index, messages, sessions, conversation_states, tasks
    assert "user_shard_index" in tables
    assert "messages" in tables


def test_migration_runner_migrates_messages(tmp_path: Path) -> None:
    """Messages should be migrated to the correct user's shard DB."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    src_db = tmp_path / "hermes_os.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            platform TEXT,
            team TEXT DEFAULT 'default'
        )
    """)
    conn.execute("""
        CREATE TABLE messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("INSERT INTO users VALUES ('u1', 'Alice', 'feishu', 'default')")
    conn.execute("INSERT INTO messages VALUES (1, 'u1', 'user', 'hello', '2024-01-01')")
    conn.execute("INSERT INTO messages VALUES (2, 'u1', 'assistant', 'hi', '2024-01-01')")
    conn.commit()
    conn.close()

    sm = ShardManager(base_path=tmp_path / "users", num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    asyncio.run(storage.migrate_from_single_db(src_db))

    u1_shard = sm.shard_index_for("u1")
    u1_path = tmp_path / "users" / f"{u1_shard:03d}" / "u1.db"

    conn2 = sqlite3.connect(str(u1_path))
    cur = conn2.execute("SELECT COUNT(*) FROM messages")
    count = cur.fetchone()[0]
    conn2.close()

    assert count == 2, f"u1 should have 2 messages, got {count}"


def test_migration_runner_wal_mode_enforced(tmp_path: Path) -> None:
    """Migrated shard DB should have WAL journal mode."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    src_db = tmp_path / "hermes_os.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            platform TEXT,
            team TEXT DEFAULT 'default'
        )
    """)
    conn.execute("INSERT INTO users VALUES ('u1', 'Alice', 'feishu', 'default')")
    conn.commit()
    conn.close()

    sm = ShardManager(base_path=tmp_path / "users", num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    asyncio.run(storage.migrate_from_single_db(src_db))

    u1_shard = sm.shard_index_for("u1")
    u1_path = tmp_path / "users" / f"{u1_shard:03d}" / "u1.db"

    conn2 = sqlite3.connect(str(u1_path))
    cur = conn2.execute("PRAGMA journal_mode")
    mode = cur.fetchone()[0]
    conn2.close()

    assert mode.upper() == "WAL", f"Expected WAL, got {mode}"


# ---------------------------------------------------------------------------
# Tests: ShardedStorage with existing users
# ---------------------------------------------------------------------------


def test_get_db_returns_sharded_connection(tmp_path: Path) -> None:
    """_get_db_for(user_id) should return a connection to that user's shard DB."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    # Create a user DB manually
    shard_idx = sm.shard_index_for("u1")
    shard_dir = tmp_path / f"{shard_idx:03d}"
    shard_dir.mkdir(parents=True)
    u1_db = shard_dir / "u1.db"

    async def setup():
        conn = await storage._get_db_for("u1")
        await conn.execute("CREATE TABLE IF NOT EXISTS test (id TEXT)")
        await conn.commit()
        return conn

    conn = asyncio.run(setup())
    assert conn is not None
    assert u1_db.exists()
