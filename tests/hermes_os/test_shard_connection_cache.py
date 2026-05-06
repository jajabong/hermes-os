"""TDD tests for ShardedStorage connection cache LRU eviction."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_os.shard_manager import ShardedStorage, ShardManager


@pytest.fixture
def sharded_storage(tmp_path: Path) -> ShardedStorage:
    sm = ShardManager(base_path=tmp_path, num_shards=10)
    return ShardedStorage(shard_manager=sm)


@pytest.mark.asyncio
async def test_connection_cache_eviction(sharded_storage: ShardedStorage) -> None:
    """When _connections exceeds MAX_CONNECTIONS, oldest entries are evicted."""
    max_conn = sharded_storage.MAX_CONNECTIONS

    # Open more connections than the max
    for i in range(max_conn + 5):
        user_id = f"user_{i:03d}"
        await sharded_storage._get_db_for(user_id)

    # Cache should not exceed MAX_CONNECTIONS
    assert len(sharded_storage._connections) <= max_conn


@pytest.mark.asyncio
async def test_connection_cache_lru_order(sharded_storage: ShardedStorage) -> None:
    """Most recently accessed connections are kept, least recent are evicted."""
    max_conn = sharded_storage.MAX_CONNECTIONS

    # Fill the cache
    for i in range(max_conn):
        await sharded_storage._get_db_for(f"user_{i:03d}")

    # Access user_000 again (makes it most recent)
    await sharded_storage._get_db_for("user_000")

    # Add a new user to trigger eviction
    await sharded_storage._get_db_for(f"user_overflow_{max_conn}")

    # user_000 should still be in cache (was re-accessed)
    assert "user_000" in sharded_storage._connections


@pytest.mark.asyncio
async def test_close_cleans_all_connections(sharded_storage: ShardedStorage) -> None:
    """close() closes all cached connections and clears the cache."""
    # Open some connections
    for i in range(5):
        await sharded_storage._get_db_for(f"user_{i:03d}")

    assert len(sharded_storage._connections) == 5

    # close() should clear everything
    await sharded_storage.close()

    assert len(sharded_storage._connections) == 0


@pytest.mark.asyncio
async def test_connection_reuse(sharded_storage: ShardedStorage) -> None:
    """Accessing the same user twice returns the same connection object."""
    conn1 = await sharded_storage._get_db_for("alice")
    conn2 = await sharded_storage._get_db_for("alice")

    # Same connection object should be returned
    assert conn1 is conn2
    assert len(sharded_storage._connections) == 1
