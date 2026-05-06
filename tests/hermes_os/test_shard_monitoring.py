"""Tests for ShardManager/ShardedStorage monitoring API."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_os.shard_manager import ShardedStorage, ShardManager


@pytest.fixture
def sm(tmp_path: Path) -> ShardManager:
    return ShardManager(base_path=tmp_path, num_shards=10)


@pytest.fixture
def sharded_storage(tmp_path: Path) -> ShardedStorage:
    sm = ShardManager(base_path=tmp_path, num_shards=10)
    return ShardedStorage(shard_manager=sm)


def test_get_stats_empty(sm: ShardManager) -> None:
    """With no users, stats should reflect empty state."""
    stats = sm.get_stats()
    assert stats["total_users"] == 0
    assert stats["total_shards_used"] == 0
    assert stats["shard_distribution"] == {}
    assert stats["total_messages"] == 0


def test_get_stats_reflects_user_count(sm: ShardManager, tmp_path: Path) -> None:
    """Stats should accurately count users across shards."""
    # Create 3 users (each in their own shard)
    for i in range(3):
        user_id = f"user_{i:03d}"
        db_path = sm.db_path_for(user_id)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER)")
        conn.close()

    stats = sm.get_stats()
    assert stats["total_users"] == 3
    assert stats["total_shards_used"] == 3
    assert len(stats["shard_distribution"]) == 3


@pytest.mark.asyncio
async def test_sharded_storage_get_stats(sharded_storage: ShardedStorage) -> None:
    """ShardedStorage.get_stats() delegates to ShardManager."""
    stats = sharded_storage.get_stats()
    assert "total_users" in stats
    assert "total_shards_used" in stats
    assert "shard_distribution" in stats
