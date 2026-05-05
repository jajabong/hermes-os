"""Tests for per-user task isolation in TaskScheduler.

User data isolation is achieved through user_id field in a shared database,
not through separate database files per user.
"""

import pytest
import os
from pathlib import Path

from hermes_os.task_scheduler import TaskScheduler, TaskStatus


class TestUserDatabasePathResolution:
    """Test TaskScheduler database path handling."""

    def test_default_db_path(self) -> None:
        """Default db_path should be hermes_os.db."""
        scheduler = TaskScheduler()
        assert scheduler.db_path == "hermes_os.db"

    def test_db_path_configurable(self) -> None:
        """db_path can be configured at construction time."""
        scheduler = TaskScheduler(db_path="/tmp/custom.db")
        assert scheduler.db_path == "/tmp/custom.db"


class TestPerUserDatabaseIsolation:
    """Test that tasks are isolated by user_id in a shared database."""

    @pytest.fixture
    def db_path(self) -> str:
        path = f"/tmp/test_isolation_{os.getpid()}.db"
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_tasks_stored_in_shared_db(self, db_path: str) -> None:
        """Tasks for different users are stored in the same database."""
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

        # Both tasks should exist in the same database
        all_tasks = await scheduler.get_all_tasks()
        all_ids = [t.task_id for t in all_tasks]
        assert alice_task.task_id in all_ids
        assert bob_task.task_id in all_ids

    @pytest.mark.asyncio
    async def test_cross_user_data_isolation(self, db_path: str) -> None:
        """Reading alice's tasks should never see bob's tasks."""
        scheduler = TaskScheduler(db_path=db_path)

        await scheduler.create_task(user_id="alice", title="Secret Alice")
        await scheduler.create_task(user_id="bob", title="Secret Bob")

        alice_tasks = await scheduler.get_tasks_for_user("alice")

        alice_task_titles = [t.title for t in alice_tasks]
        assert "Secret Bob" not in alice_task_titles
        assert "Secret Alice" in alice_task_titles


class TestAllUsersDatabaseScanning:
    """Test cross-user query capabilities."""

    @pytest.fixture
    def db_path(self) -> str:
        path = f"/tmp/test_scan_{os.getpid()}.db"
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_get_all_tasks_returns_all_users(self, db_path: str) -> None:
        """get_all_tasks should return tasks from all users."""
        scheduler = TaskScheduler(db_path=db_path)

        await scheduler.create_task(user_id="alice", title="Alice task")
        await scheduler.create_task(user_id="bob", title="Bob task")

        all_tasks = await scheduler.get_all_tasks()
        titles = [t.title for t in all_tasks]
        assert "Alice task" in titles
        assert "Bob task" in titles

    @pytest.mark.asyncio
    async def test_get_tasks_for_user_filtered_by_status(self, db_path: str) -> None:
        """get_tasks_for_user can filter by status."""
        scheduler = TaskScheduler(db_path=db_path)

        t1 = await scheduler.create_task(user_id="alice", title="Pending task")
        await scheduler.update_task_status(t1.task_id, TaskStatus.COMPLETED)

        pending = await scheduler.get_tasks_for_user("alice", status=TaskStatus.PENDING)
        completed = await scheduler.get_tasks_for_user("alice", status=TaskStatus.COMPLETED)

        pending_titles = [t.title for t in pending]
        completed_titles = [t.title for t in completed]

        assert "Pending task" not in pending_titles
        assert "Pending task" in completed_titles
