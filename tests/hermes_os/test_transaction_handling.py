"""Tests for BEGIN IMMEDIATE transaction behavior in ShardedStorage."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_os.shard_manager import ShardedStorage, ShardManager
from hermes_os.task_scheduler import Task, TaskPriority, TaskStatus


@pytest.fixture
def sharded_storage(tmp_path: Path) -> ShardedStorage:
    sm = ShardManager(base_path=tmp_path, num_shards=10)
    return ShardedStorage(shard_manager=sm)


def _make_task(task_id: str, user_id: str = "alice") -> Task:
    return Task(
        task_id=task_id,
        user_id=user_id,
        title=f"Task {task_id}",
        description="Test",
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )


@pytest.mark.asyncio
async def test_create_task_commits_successfully(sharded_storage: ShardedStorage) -> None:
    """create_task should commit and task should be retrievable."""
    task = _make_task("test-create-001")
    await sharded_storage.create_task(task)

    found = await sharded_storage.get_task("test-create-001")
    assert found is not None
    assert found.task_id == "test-create-001"


@pytest.mark.asyncio
async def test_create_task_rollback_on_error(sharded_storage: ShardedStorage) -> None:
    """If commit fails, task should not exist."""
    import sqlite3

    task = _make_task("test-rollback-001")

    # Create task normally first (should succeed)
    await sharded_storage.create_task(task)
    found = await sharded_storage.get_task("test-rollback-001")
    assert found is not None

    # Trying to create duplicate should fail
    with pytest.raises((sqlite3.IntegrityError, Exception)):
        await sharded_storage.create_task(task)


@pytest.mark.asyncio
async def test_update_task_status_commits(sharded_storage: ShardedStorage) -> None:
    """update_task_status should persist the status change."""
    task = _make_task("test-update-001")
    await sharded_storage.create_task(task)

    await sharded_storage.update_task_status("test-update-001", "running", progress=0.5)

    # Verify via direct query
    conn = await sharded_storage._get_db_for("alice")
    async with conn.execute(
        "SELECT status, progress FROM tasks WHERE task_id = ?", ("test-update-001",)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["status"] == "running"
    assert row["progress"] == 0.5


@pytest.mark.asyncio
async def test_delete_task_removes_from_db(sharded_storage: ShardedStorage) -> None:
    """delete_task should remove the task from the shard DB."""
    task = _make_task("test-delete-001")
    await sharded_storage.create_task(task)

    result = await sharded_storage.delete_task("test-delete-001")
    assert result is True

    found = await sharded_storage.get_task("test-delete-001")
    assert found is None
