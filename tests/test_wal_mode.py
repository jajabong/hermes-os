"""Tests for WAL mode enforcement on SQLite connections."""

import os
import tempfile

import pytest

from hermes_os.storage import Storage
from hermes_os.task_scheduler import TaskScheduler


class TestStorageWALMode:
    @pytest.fixture
    def db_path(self) -> str:
        path = tempfile.mktemp(suffix=".db")
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_storage_connection_uses_wal_mode(self, db_path: str) -> None:
        storage = Storage(db_path=db_path)
        await storage.initialize()
        db = await storage._get_db()
        async with db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0].upper() == "WAL", f"Expected WAL, got {row[0]}"
        await storage.close()

    @pytest.mark.asyncio
    async def test_storage_connection_uses_normal_synchronous(self, db_path: str) -> None:
        storage = Storage(db_path=db_path)
        await storage.initialize()
        db = await storage._get_db()
        async with db.execute("PRAGMA synchronous") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert int(row[0]) == 1, f"Expected synchronous=NORMAL (1), got {row[0]}"
        await storage.close()


class TestTaskSchedulerWALMode:
    @pytest.fixture
    def db_path(self) -> str:
        path = tempfile.mktemp(suffix=".db")
        yield path
        for p in [path, path + "-wal", path + "-shm"]:
            if os.path.exists(p):
                os.remove(p)

    @pytest.mark.asyncio
    async def test_scheduler_initializes_db(self, db_path: str) -> None:
        """TaskScheduler creates its database and tables on first use."""
        scheduler = TaskScheduler(db_path=db_path)
        # Trigger lazy init by creating a task
        task = await scheduler.create_task(user_id="alice", title="Test", description="")
        assert task.task_id is not None
        assert task.status.value == "pending"
        # Database should be accessible
        db = await scheduler._get_db()
        assert db is not None
