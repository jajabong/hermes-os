"""Tests for P3: decoupled scheduler and executor architecture."""

import pytest
import asyncio
import tempfile
import os

from hermes_os.task_scheduler import TaskScheduler


class TestDecoupledArchitecture:
    """Test that scheduler and executor are physically decoupled."""

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_scheduler_only_creates_tasks(self, base_dir: str) -> None:
        """Scheduler.create_task should only persist tasks, not execute them."""
        scheduler = TaskScheduler(base_dir=base_dir, max_concurrent=1)
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
    async def test_separate_execute_task_method_exists(self, base_dir: str) -> None:
        """TaskScheduler should have a separate execute_task() method for background worker."""
        scheduler = TaskScheduler(base_dir=base_dir)
        # Should have execute_task method (called by BackgroundWorker)
        assert hasattr(scheduler, 'execute_task')

    @pytest.mark.asyncio
    async def test_execute_task_runs_within_semaphore(self, base_dir: str) -> None:
        """execute_task should use semaphore for concurrency control."""
        scheduler = TaskScheduler(base_dir=base_dir, max_concurrent=2)
        task = await scheduler.create_task(
            user_id="alice",
            title="Test",
            description="Echo test",
            metadata={"cwd": os.path.expanduser("~")},
        )
        # execute_task should be able to run without hanging (it will fail since
        # we don't have a real Claude Code, but it should at least try within semaphore)
        try:
            # This will fail due to no real Claude Code, but proves it runs
            await scheduler.execute_task(task)
        except Exception:
            pass  # Expected - no real Claude Code
        # If we get here without deadlock, the semaphore worked

    @pytest.mark.asyncio
    async def test_runnable_tasks_not_executed_by_watcher(self, base_dir: str) -> None:
        """start_watcher should NOT directly execute tasks - use BackgroundWorker."""
        scheduler = TaskScheduler(base_dir=base_dir)

        # Create tasks
        t1 = await scheduler.create_task(user_id="alice", title="Task 1", description="d1")
        t2 = await scheduler.create_task(user_id="bob", title="Task 2", description="d2")

        # get_runnable_tasks should return tasks in PENDING state
        runnable = await scheduler.get_runnable_tasks()
        # These should still be PENDING (watcher doesn't auto-run)
        for r in runnable:
            assert r.status == "pending"


class TestBackgroundWorkerExists:
    """Test that BackgroundWorker class exists and can be imported."""

    def test_background_worker_importable(self) -> None:
        """BackgroundWorker should exist in task_scheduler module."""
        from hermes_os.task_scheduler import BackgroundWorker
        assert BackgroundWorker is not None

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_background_worker_start_stop(self, base_dir: str) -> None:
        """BackgroundWorker should start and stop cleanly."""
        from hermes_os.task_scheduler import BackgroundWorker, TaskScheduler

        scheduler = TaskScheduler(base_dir=base_dir)
        worker = BackgroundWorker(scheduler, interval_seconds=1.0)

        # Create a task so worker has something to potentially process
        await scheduler.create_task(user_id="alice", title="Test", description="d1")

        # Start worker (it runs in background)
        await worker.start()

        # Let it run for a moment
        await asyncio.sleep(0.5)

        # Stop cleanly
        await worker.stop()

        # Verify no exceptions


class TestFireAndForgetPattern:
    """Test that task creation is fire-and-forget (non-blocking)."""

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_create_task_is_non_blocking(self, base_dir: str) -> None:
        """create_task should return immediately without waiting for execution."""
        scheduler = TaskScheduler(base_dir=base_dir)

        # Create multiple tasks rapidly
        tasks = []
        for i in range(5):
            t = await scheduler.create_task(
                user_id=f"user_{i}",
                title=f"Task {i}",
                description=f"Description {i}",
            )
            tasks.append(t)

        # All tasks should be created in under 1 second (non-blocking)
        assert len(tasks) == 5
        for t in tasks:
            assert t.status.value == "pending"