"""Tests for shard_manager.py — TDD for physical user sharding."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from hermes_os.shard_manager import ShardManager, ShardedStorage


# ---------------------------------------------------------------------------
# ShardManager tests
# ---------------------------------------------------------------------------

def test_shard_index_is_deterministic() -> None:
    """Same user_id must always map to the same shard index."""
    sm = ShardManager(num_shards=100)
    uid = "user_abc123"
    idx1 = sm.shard_index_for(uid)
    idx2 = sm.shard_index_for(uid)
    assert idx1 == idx2


def test_shard_index_is_in_range() -> None:
    """Shard index must be in [0, num_shards-1]."""
    sm = ShardManager(num_shards=100)
    for i in range(500):
        uid = f"user_{i:04d}"
        idx = sm.shard_index_for(uid)
        assert 0 <= idx < 100


def test_users_distributed_across_shards() -> None:
    """100 users should spread across many shards, not all on one."""
    sm = ShardManager(num_shards=100)
    indices = {sm.shard_index_for(f"user_{i:03d}") for i in range(100)}
    # With 100 users and 100 shards, expect roughly 60%+ unique shards
    assert len(indices) >= 50


def test_db_path_structure() -> None:
    """db_path_for() should produce path like ~/.hermes/users/{shard:03d}/{user_id}.db."""
    sm = ShardManager(num_shards=100, base_path=Path("/tmp/hermes_test_users"))
    path = sm.db_path_for("user_abc")
    parts = path.parts
    assert f"{sm.shard_index_for('user_abc'):03d}" in str(path)
    assert path.suffix == ".db"
    assert "user_abc.db" in str(path)


def test_shard_dir_auto_created_on_first_access(tmp_path: Path) -> None:
    """Shard directory should be created automatically when accessing a user."""
    sm = ShardManager(base_path=tmp_path, num_shards=100)
    uid = "test_user_xyz"
    path = sm.db_path_for(uid)
    # Path should exist after getting the path (not after DB open yet)
    # The parent dir creation happens in ShardedStorage._get_db_for
    assert path.parent == tmp_path / f"{sm.shard_index_for(uid):03d}"


# ---------------------------------------------------------------------------
# ShardedStorage tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sharded_storage(tmp_path: Path) -> ShardedStorage:
    sm = ShardManager(base_path=tmp_path, num_shards=10)
    return ShardedStorage(shard_manager=sm)


@pytest.mark.asyncio
async def test_get_db_creates_shard_dir(sharded_storage: ShardedStorage) -> None:
    """Opening a DB should auto-create the shard directory."""
    uid = "user_init_test"
    db = await sharded_storage._get_db_for(uid)
    assert db is not None
    # The shard directory should now exist
    shard_idx = sharded_storage.shard_manager.shard_index_for(uid)
    expected_dir = sharded_storage.shard_manager.BASE_PATH / f"{shard_idx:03d}"
    assert expected_dir.exists()


@pytest.mark.asyncio
async def test_wal_mode_enabled_on_shard_db(sharded_storage: ShardedStorage) -> None:
    """Shard DB should have WAL mode enabled."""
    uid = "user_wal_test"
    db = await sharded_storage._get_db_for(uid)
    async with db.execute("PRAGMA journal_mode") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "wal"


@pytest.mark.asyncio
async def test_different_users_get_different_connections(sharded_storage: ShardedStorage) -> None:
    """Two different users should get connections to different DB files."""
    uid_a = "user_a_001"
    uid_b = "user_b_002"
    db_a = await sharded_storage._get_db_for(uid_a)
    db_b = await sharded_storage._get_db_for(uid_b)
    # Same shard? maybe, maybe not. But they are different connections
    assert db_a is not db_b


@pytest.mark.asyncio
async def test_same_user_returns_same_connection(sharded_storage: ShardedStorage) -> None:
    """Same user should get the same connection on repeated calls."""
    uid = "user_reuse_test"
    db1 = await sharded_storage._get_db_for(uid)
    db2 = await sharded_storage._get_db_for(uid)
    assert db1 is db2


@pytest.mark.asyncio
async def test_lazy_init_creates_tables(sharded_storage: ShardedStorage) -> None:
    """_lazy_initialize should create the user_shard_index table."""
    uid = "user_table_test"
    db = await sharded_storage._get_db_for(uid)
    # Check the table exists
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_shard_index'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "user_shard_index"


@pytest.mark.asyncio
async def test_insert_and_query_user_in_shard(sharded_storage: ShardedStorage) -> None:
    """Should be able to write and read user data in a shard."""
    uid = "user_insert_test"
    db = await sharded_storage._get_db_for(uid)

    await db.execute(
        "INSERT OR REPLACE INTO user_shard_index (user_id, shard_hint, created_at) VALUES (?, ?, ?)",
        (uid, 0, "2026-01-01T00:00:00"),
    )
    await db.commit()

    async with db.execute(
        "SELECT * FROM user_shard_index WHERE user_id = ?", (uid,)
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row["user_id"] == uid
    assert row["shard_hint"] == 0


@pytest.mark.asyncio
async def test_multiple_users_in_same_shard(sharded_storage: ShardedStorage) -> None:
    """Different users have separate DB files and separate connections, regardless of shard."""
    # Use user IDs we know hash to different shards (via the 10-shard fixture)
    uid_a = "alice_user_0001"
    uid_b = "bob_user_0002"

    sm = sharded_storage.shard_manager

    # Each user gets their own DB file
    path_a = sm.db_path_for(uid_a)
    path_b = sm.db_path_for(uid_b)
    assert path_a != path_b  # Different user files

    # Each user gets their own connection
    db_a = await sharded_storage._get_db_for(uid_a)
    db_b = await sharded_storage._get_db_for(uid_b)
    assert db_a is not db_b  # Separate connections for separate files

    # We can write to both independently
    shard_idx_a = sm.shard_index_for(uid_a)
    shard_idx_b = sm.shard_index_for(uid_b)

    await db_a.execute(
        "INSERT OR REPLACE INTO user_shard_index (user_id, shard_hint, created_at) VALUES (?, ?, ?)",
        (uid_a, shard_idx_a, "2026-01-01"),
    )
    await db_a.commit()

    await db_b.execute(
        "INSERT OR REPLACE INTO user_shard_index (user_id, shard_hint, created_at) VALUES (?, ?, ?)",
        (uid_b, shard_idx_b, "2026-01-02"),
    )
    await db_b.commit()

    # Verify both exist in their respective DBs
    async with db_a.execute("SELECT user_id FROM user_shard_index WHERE user_id = ?", (uid_a,)) as cur:
        row_a = await cur.fetchone()
    async with db_b.execute("SELECT user_id FROM user_shard_index WHERE user_id = ?", (uid_b,)) as cur:
        row_b = await cur.fetchone()

    assert row_a is not None
    assert row_b is not None