"""Tests for WAL mode enforcement on all SQLite connections."""

import pytest
import os
import tempfile

from hermes_os.storage import Storage
from hermes_os.task_scheduler import TaskScheduler


class TestStorageWALMode:
    @pytest.fixture
    def db_path(self) -> str:
        path = tempfile.mktemp(suffix=".db")
        yield path
        if os.path.exists(path):
            os.remove(path)

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
    def base_dir(self) -> str:
        path = tempfile.mkdtemp()
        yield path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_scheduler_user_db_uses_wal_mode(self, base_dir: str) -> None:
        """TaskScheduler._get_user_db() should enable WAL mode."""
        scheduler = TaskScheduler(base_dir=base_dir)
        # Trigger user db creation
        await scheduler.create_task(user_id="alice", title="test", description="test")
        db = await scheduler._get_user_db("alice")
        async with db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0].upper() == "WAL", f"Expected WAL, got {row[0]}"

    @pytest.mark.asyncio
    async def test_scheduler_user_db_uses_normal_synchronous(self, base_dir: str) -> None:
        """TaskScheduler._get_user_db() should set PRAGMA synchronous=NORMAL."""
        scheduler = TaskScheduler(base_dir=base_dir)
        await scheduler.create_task(user_id="alice", title="test", description="test")
        db = await scheduler._get_user_db("alice")
        async with db.execute("PRAGMA synchronous") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert int(row[0]) == 1, f"Expected synchronous=NORMAL (1), got {row[0]}"

    @pytest.mark.asyncio
    async def test_multiple_user_dbs_all_use_wal(self, base_dir: str) -> None:
        """Multiple user databases should all open WAL mode."""
        scheduler = TaskScheduler(base_dir=base_dir)
        await scheduler.create_task(user_id="alice", title="test1", description="d1")
        await scheduler.create_task(user_id="bob", title="test2", description="d2")

        db_alice = await scheduler._get_user_db("alice")
        db_bob = await scheduler._get_user_db("bob")

        for db, name in [(db_alice, "alice"), (db_bob, "bob")]:
            async with db.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
                assert row is not None
                assert row[0].upper() == "WAL", f"{name} expected WAL, got {row[0]}"