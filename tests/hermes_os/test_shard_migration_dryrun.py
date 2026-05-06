"""Tests for shard migration dry run — verify migration correctness before execution."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path


def test_migration_produces_correct_user_shards() -> None:
    """hermes_os.db users should land in expected shards per ShardManager."""
    from hermes_os.shard_manager import ShardManager

    sm = ShardManager()

    # Users from hermes_os.db
    users = [
        ("479258a52207b454", "Dana"),
        ("33213d120aac37cc", "Eve"),
        ("de97b03526100b28", "Charlie New"),
        ("53eb6e1d86f1c172", "FallbackUser"),
        ("d4d7ff6a59918da8", "Test"),
    ]

    for user_id, name in users:
        shard = sm.shard_index_for(user_id)
        assert 0 <= shard < 100
        path = sm.db_path_for(user_id)
        assert f"{shard:03d}" in str(path)
        assert str(user_id) in str(path)


def test_migration_dry_run_migrates_all_tables(tmp_path: Path) -> None:
    """Dry run should migrate users, messages, sessions, conversation_states."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    # Create source DB with all expected tables
    src_db = tmp_path / "hermes_os.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            role TEXT,
            team TEXT,
            platform TEXT,
            platform_user_id TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE sessions (
            user_id TEXT PRIMARY KEY,
            session_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE conversation_states (
            user_id TEXT PRIMARY KEY,
            state TEXT,
            current_task_id TEXT,
            pending_decision TEXT,
            multi_step_progress REAL,
            last_updated TEXT,
            metadata TEXT
        )
    """)
    conn.execute(
        "INSERT INTO users VALUES ('u_dryrun', 'DryRunUser', 'user', 'default', 'feishu', 'ou_test', '2026-01-01')"
    )
    conn.execute("INSERT INTO messages VALUES (1, 'u_dryrun', 'user', 'hello', '2026-01-01')")
    conn.execute("INSERT INTO sessions VALUES ('u_dryrun', 'sess_dryrun')")
    conn.commit()
    conn.close()

    sm = ShardManager(base_path=tmp_path / "users", num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    asyncio.run(storage.migrate_from_single_db(src_db))

    # Verify the user landed in correct shard
    shard = sm.shard_index_for("u_dryrun")
    user_db = tmp_path / "users" / f"{shard:03d}" / "u_dryrun.db"
    assert user_db.exists()

    # Verify messages migrated
    conn2 = sqlite3.connect(str(user_db))
    cur = conn2.execute("SELECT COUNT(*) FROM messages")
    count = cur.fetchone()[0]
    conn2.close()
    assert count == 1


def test_migration_handles_empty_source_tables(tmp_path: Path) -> None:
    """Migration should not fail if some tables are empty."""
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    src_db = tmp_path / "minimal.db"
    conn = sqlite3.connect(str(src_db))
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            role TEXT,
            team TEXT,
            platform TEXT,
            platform_user_id TEXT,
            created_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO users VALUES ('only_user', 'OnlyUser', 'user', 'default', 'feishu', 'ou_only', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    sm = ShardManager(base_path=tmp_path / "users", num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    # Should not raise
    asyncio.run(storage.migrate_from_single_db(src_db))

    shard = sm.shard_index_for("only_user")
    user_db = tmp_path / "users" / f"{shard:03d}" / "only_user.db"
    assert user_db.exists()
