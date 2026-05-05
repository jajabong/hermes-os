"""TDD tests for ShardedStorage task shard cache.

The cache stores task_id → shard_db_name mappings to avoid O(n) scans.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from hermes_os.shard_manager import ShardManager, ShardedStorage
from hermes_os.task_scheduler import Task, TaskStatus, TaskPriority


@pytest.fixture
def sharded_storage(tmp_path: Path) -> ShardedStorage:
    sm = ShardManager(base_path=tmp_path, num_shards=10)
    return ShardedStorage(shard_manager=sm)


def _make_task(task_id: str, user_id: str = "alice") -> Task:
    """Helper to create a Task for testing."""
    return Task(
        task_id=task_id,
        user_id=user_id,
        title=f"Test task {task_id}",
        description="Test description",
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )


@pytest.mark.asyncio
async def test_get_task_populates_cache(sharded_storage: ShardedStorage) -> None:
    """After get_task finds a task, cache is populated."""
    task = _make_task("t-cache-test-001", "alice")
    await sharded_storage.create_task(task)

    # Prime the cache via get_task
    found = await sharded_storage.get_task("t-cache-test-001")
    assert found is not None

    # Cache should now have the mapping
    cache = sharded_storage._task_shard_cache
    assert "t-cache-test-001" in cache
    # db_name is the user_id (alice's db stem = "alice")
    assert cache["t-cache-test-001"] == "alice"


@pytest.mark.asyncio
async def test_get_task_uses_cache_not_scan(sharded_storage: ShardedStorage) -> None:
    """Second get_task call should hit cache, not do a full scan."""
    task = _make_task("t-cache-hit-001", "alice")
    await sharded_storage.create_task(task)

    # First call — populates cache
    await sharded_storage.get_task("t-cache-hit-001")

    import unittest.mock as mock

    with mock.patch.object(sharded_storage, "_scan_all_shards_for_task", new_callable=mock.AsyncMock) as mock_scan:
        mock_scan.return_value = None
        result = await sharded_storage.get_task("t-cache-hit-001")

    # Cache hit returns result without scanning
    assert result is not None
    mock_scan.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_invalidates_cache_miss(sharded_storage: ShardedStorage) -> None:
    """Cache miss on create — no invalidation needed since task is new."""
    task = _make_task("t-new-task-001", "alice")
    await sharded_storage.create_task(task)

    # Cache miss is expected for new task (create does not pre-populate cache)
    cache = sharded_storage._task_shard_cache
    assert "t-new-task-001" not in cache


@pytest.mark.asyncio
async def test_update_task_status_uses_cache(sharded_storage: ShardedStorage) -> None:
    """update_task_status should use cache for shard lookup, not scan all shards."""
    task = _make_task("t-update-cache-001", "alice")
    await sharded_storage.create_task(task)

    # Populate cache
    await sharded_storage.get_task("t-update-cache-001")

    import unittest.mock as mock

    with mock.patch.object(sharded_storage, "_scan_all_shards_for_task", new_callable=mock.AsyncMock) as mock_scan:
        mock_scan.return_value = None
        await sharded_storage.update_task_status("t-update-cache-001", "running", progress=0.5)

    mock_scan.assert_not_called()


@pytest.mark.asyncio
async def test_delete_task_clears_cache(sharded_storage: ShardedStorage) -> None:
    """Deleting a task removes it from the cache."""
    task = _make_task("t-delete-cache-001", "alice")
    await sharded_storage.create_task(task)

    # Prime the cache
    await sharded_storage.get_task("t-delete-cache-001")
    assert "t-delete-cache-001" in sharded_storage._task_shard_cache

    # Delete
    result = await sharded_storage.delete_task("t-delete-cache-001")
    assert result is True

    # Cache entry removed
    assert "t-delete-cache-001" not in sharded_storage._task_shard_cache


@pytest.mark.asyncio
async def test_delete_task_unknown_is_noop(sharded_storage: ShardedStorage) -> None:
    """Deleting a non-existent task returns False, doesn't raise."""
    result = await sharded_storage.delete_task("nonexistent-task-xyz")
    assert result is False


@pytest.mark.asyncio
async def test_get_task_cache_miss_then_hit(sharded_storage: ShardedStorage) -> None:
    """First get_task is cache miss (scan), second is cache hit."""
    task = _make_task("t-miss-hit-001", "alice")
    await sharded_storage.create_task(task)

    # First call - cache miss triggers real scan
    result1 = await sharded_storage.get_task("t-miss-hit-001")
    assert result1 is not None
    assert "t-miss-hit-001" in sharded_storage._task_shard_cache

    # Second call - cache hit, scan NOT called
    import unittest.mock as mock

    with mock.patch.object(sharded_storage, "_scan_all_shards_for_task", new_callable=mock.AsyncMock) as mock_scan:
        mock_scan.return_value = None
        result2 = await sharded_storage.get_task("t-miss-hit-001")
        assert result2 is not None
        mock_scan.assert_not_called()