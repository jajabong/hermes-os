"""Tests for TaskScheduler concurrent task creation and isolation."""

import pytest
import asyncio
import os

from hermes_os.task_scheduler import TaskScheduler, TaskStatus


class TestConcurrencySemaphore:
    """Test TaskScheduler concurrent task operations."""

    @pytest.fixture
    def db_path(self) -> str:
        path = f"/tmp/test_concurrency_{os.getpid()}.db"
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_concurrent_task_creation(self, db_path: str) -> None:
        """Many tasks can be created concurrently without conflicts."""
        scheduler = TaskScheduler(db_path=db_path)
        tasks = await asyncio.gather(*[
            scheduler.create_task(user_id=f"u{i}", title=f"Task {i}", description=f"Desc {i}")
            for i in range(20)
        ])
        assert len(tasks) == 20
        for t in tasks:
            assert t.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_tasks_created_and_retrieved_with_isolation(self, db_path: str) -> None:
        """Verify tasks for different users are correctly isolated."""
        scheduler = TaskScheduler(db_path=db_path)
        alice_task = await scheduler.create_task(
            user_id="alice",
            title="Alice task",
            description="Alice's work",
        )
        bob_task = await scheduler.create_task(
            user_id="bob",
            title="Bob task",
            description="Bob's work",
        )

        assert alice_task.user_id == "alice"
        assert bob_task.user_id == "bob"

        retrieved_alice = await scheduler.get_task(alice_task.task_id)
        retrieved_bob = await scheduler.get_task(bob_task.task_id)
        assert retrieved_alice is not None
        assert retrieved_alice.task_id == alice_task.task_id
        assert retrieved_bob is not None
        assert retrieved_bob.task_id == bob_task.task_id

    @pytest.mark.asyncio
    async def test_get_tasks_for_user_respects_user_id(self, db_path: str) -> None:
        """get_tasks_for_user should only return that user's tasks."""
        scheduler = TaskScheduler(db_path=db_path)
        await scheduler.create_task(user_id="alice", title="Alice 1", description="")
        await scheduler.create_task(user_id="alice", title="Alice 2", description="")
        await scheduler.create_task(user_id="bob", title="Bob 1", description="")

        alice_tasks = await scheduler.get_tasks_for_user("alice")
        alice_titles = [t.title for t in alice_tasks]
        assert "Alice 1" in alice_titles
        assert "Alice 2" in alice_titles
        assert "Bob 1" not in alice_titles

    @pytest.mark.asyncio
    async def test_get_all_tasks_returns_all_users(self, db_path: str) -> None:
        """get_all_tasks should return tasks from all users."""
        scheduler = TaskScheduler(db_path=db_path)
        await scheduler.create_task(user_id="alice", title="A-task", description="")
        await scheduler.create_task(user_id="bob", title="B-task", description="")

        all_tasks = await scheduler.get_all_tasks()
        titles = [t.title for t in all_tasks]
        assert "A-task" in titles
        assert "B-task" in titles
