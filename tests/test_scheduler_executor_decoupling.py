"""Tests for scheduler and executor decoupled architecture.

TaskScheduler.create_task only persists — execution is handled separately.
"""

import os

import pytest

from hermes_os.task_scheduler import TaskScheduler, TaskStatus


class TestDecoupledArchitecture:
    """Test that scheduler and executor are physically decoupled."""

    @pytest.fixture
    def db_path(self) -> str:
        path = f"/tmp/test_decouple_{os.getpid()}.db"
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_scheduler_only_creates_tasks(self, db_path: str) -> None:
        """Scheduler.create_task should only persist tasks, not execute them."""
        scheduler = TaskScheduler(db_path=db_path)
        task = await scheduler.create_task(
            user_id="alice",
            title="Test task",
            description="Do something",
        )
        # Task should be in PENDING state, not RUNNING
        assert task.status.value == "pending"
        # No execution should have happened
        retrieved = await scheduler.get_task(task.task_id)
        assert retrieved is not None
        assert retrieved.status.value == "pending"

    @pytest.mark.asyncio
    async def test_get_runnable_tasks_returns_pending(self, db_path: str) -> None:
        """get_runnable_tasks should return PENDING tasks with no blockers."""
        scheduler = TaskScheduler(db_path=db_path)

        # Create tasks
        t1 = await scheduler.create_task(user_id="alice", title="Task 1", description="d1")
        t2 = await scheduler.create_task(user_id="bob", title="Task 2", description="d2")

        # get_runnable_tasks should return tasks in PENDING state
        runnable = await scheduler.get_runnable_tasks()
        runnable_ids = [r.task_id for r in runnable]
        # These should still be PENDING (scheduler doesn't auto-run)
        assert t1.task_id in runnable_ids
        assert t2.task_id in runnable_ids
        for r in runnable:
            assert r.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_task_remains_pending_until_explicit_update(self, db_path: str) -> None:
        """A task should stay PENDING even after being retrieved."""
        scheduler = TaskScheduler(db_path=db_path)
        task = await scheduler.create_task(user_id="alice", title="Test", description="")

        retrieved = await scheduler.get_task(task.task_id)
        assert retrieved.status == TaskStatus.PENDING

        # Manually update to RUNNING to simulate execution start
        await scheduler.update_task_status(task.task_id, TaskStatus.RUNNING)
        updated = await scheduler.get_task(task.task_id)
        assert updated.status == TaskStatus.RUNNING


class TestTaskStatusTransitions:
    """Test task status lifecycle transitions."""

    @pytest.fixture
    def db_path(self) -> str:
        path = f"/tmp/test_status_{os.getpid()}.db"
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_update_task_to_running(self, db_path: str) -> None:
        """update_task_status can move task to RUNNING."""
        scheduler = TaskScheduler(db_path=db_path)
        task = await scheduler.create_task(user_id="alice", title="Test", description="")
        await scheduler.update_task_status(task.task_id, TaskStatus.RUNNING)
        updated = await scheduler.get_task(task.task_id)
        assert updated.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_task_to_completed(self, db_path: str) -> None:
        """update_task_status can move task to COMPLETED with result."""
        scheduler = TaskScheduler(db_path=db_path)
        task = await scheduler.create_task(user_id="alice", title="Test", description="")
        await scheduler.update_task_status(
            task.task_id, TaskStatus.COMPLETED, result="Done successfully"
        )
        updated = await scheduler.get_task(task.task_id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "Done successfully"

    @pytest.mark.asyncio
    async def test_update_task_to_failed(self, db_path: str) -> None:
        """update_task_status can move task to FAILED with error."""
        scheduler = TaskScheduler(db_path=db_path)
        task = await scheduler.create_task(user_id="alice", title="Test", description="")
        await scheduler.update_task_status(
            task.task_id, TaskStatus.FAILED, error="Something went wrong"
        )
        updated = await scheduler.get_task(task.task_id)
        assert updated.status == TaskStatus.FAILED
        assert updated.error == "Something went wrong"
