"""Tests for per-user database sharding in TaskScheduler.

Design: ~/.hermes/users/{user_id}/tasks.db for per-user isolation.
Global db (hermes_os.db) remains for cross-user queries.
"""

import pytest
import os
import tempfile
from pathlib import Path

from hermes_os.task_scheduler import TaskScheduler, TaskPriority


class TestUserDatabasePathResolution:
    """Test that TaskScheduler resolves user-specific db paths correctly."""

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        # cleanup
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    def test_default_base_dir_is_hermes_users(self) -> None:
        """Default base_dir should be ~/.hermes/users/"""
        scheduler = TaskScheduler()
        assert "hermes" in scheduler.base_dir
        assert "users" in scheduler.base_dir

    def test_base_dir_configurable(self, base_dir: str) -> None:
        """base_dir can be configured at construction time."""
        scheduler = TaskScheduler(base_dir=base_dir)
        assert scheduler.base_dir == base_dir

    def test_user_db_path_derived_from_user_id(self, base_dir: str) -> None:
        """User db path is: base_dir/{user_id}/tasks.db"""
        scheduler = TaskScheduler(base_dir=base_dir)
        path = scheduler.get_user_db_path("alice")
        assert "alice" in path
        assert path.endswith("tasks.db")

    def test_different_users_have_different_paths(self, base_dir: str) -> None:
        """alice and bob should get different db paths."""
        scheduler = TaskScheduler(base_dir=base_dir)
        alice_path = scheduler.get_user_db_path("alice")
        bob_path = scheduler.get_user_db_path("bob")
        assert alice_path != bob_path

    def test_user_db_path_creates_directory(self, base_dir: str) -> None:
        """get_user_db_path should create parent directory if needed."""
        scheduler = TaskScheduler(base_dir=base_dir)
        path = scheduler.get_user_db_path("alice")
        assert Path(path).parent.exists()


class TestPerUserDatabaseIsolation:
    """Test that tasks are isolated per user database."""

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_tasks_stored_in_user_specific_db(self, base_dir: str) -> None:
        """Alice's tasks should be in alice's db, not bob's db."""
        scheduler = TaskScheduler(base_dir=base_dir)

        # Create tasks for alice and bob
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

        # Alice's db should contain only alice's tasks
        alice_db_path = scheduler.get_user_db_path("alice")
        import sqlite3
        conn = sqlite3.connect(alice_db_path)
        cursor = conn.execute(
            "SELECT title FROM tasks WHERE user_id = ?", ("alice",)
        )
        alice_titles = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "Alice task" in alice_titles
        assert "Bob task" not in alice_titles

    @pytest.mark.asyncio
    async def test_cross_user_data_isolation(self, base_dir: str) -> None:
        """Reading alice's db should never see bob's tasks."""
        scheduler = TaskScheduler(base_dir=base_dir)

        await scheduler.create_task(user_id="alice", title="Secret Alice")
        await scheduler.create_task(user_id="bob", title="Secret Bob")

        alice_tasks = await scheduler.get_tasks_for_user("alice")

        # alice should NOT see bob's task
        alice_task_titles = [t.title for t in alice_tasks]
        assert "Secret Bob" not in alice_task_titles
        assert "Secret Alice" in alice_task_titles


class TestAllUsersDatabaseScanning:
    """Test that BackgroundWorker can discover all user databases."""

    @pytest.fixture
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_get_all_user_ids_returns_existing_users(self, base_dir: str) -> None:
        """get_all_user_ids should return user_ids that have db files."""
        scheduler = TaskScheduler(base_dir=base_dir)

        # Create tasks for alice and bob
        await scheduler.create_task(user_id="alice", title="A")
        await scheduler.create_task(user_id="bob", title="B")

        user_ids = await scheduler.get_all_user_ids()

        assert "alice" in user_ids
        assert "bob" in user_ids

    @pytest.mark.asyncio
    async def test_get_all_runnable_tasks_scans_all_user_dbs(self, base_dir: str) -> None:
        """get_all_runnable_tasks should find tasks across all user databases."""
        scheduler = TaskScheduler(base_dir=base_dir)

        # Create pending tasks for two users
        await scheduler.create_task(user_id="alice", title="Alice task")
        await scheduler.create_task(user_id="bob", title="Bob task")

        # Should find tasks from both users
        all_tasks = await scheduler.get_all_tasks()
        titles = [t.title for t in all_tasks]
        assert "Alice task" in titles
        assert "Bob task" in titles