"""Tests for Storage — schema and query correctness."""

import pytest

from hermes_os.storage import Storage


@pytest.fixture
async def db() -> Storage:
    storage = Storage(db_path=":memory:")
    await storage.initialize()
    return storage


class TestMessagesSchema:
    """Schema validation for messages table."""

    @pytest.mark.asyncio
    async def test_messages_table_has_user_timestamp_index(self, db: Storage) -> None:
        """messages table has an index on (user_id, timestamp) for efficient queries."""
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
        )
        rows = await cursor.fetchall()
        index_names = [r["name"] for r in rows]

        # At least one index covering user_id should exist
        user_idxs = [n for n in index_names if "user" in n.lower() and "id" in n.lower()]
        assert len(user_idxs) >= 1, (
            f"Expected index on user_id column in messages table. "
            f"Found indexes: {index_names}"
        )

    @pytest.mark.asyncio
    async def test_messages_index_is_composite_user_id_timestamp(
        self, db: Storage
    ) -> None:
        """The index covers both user_id and timestamp for ORDER BY queries."""
        cursor = await db._db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
        )
        rows = await cursor.fetchall()
        index_sqls = {r["name"]: r["sql"] for r in rows if r["sql"]}

        # Should have an index on (user_id, timestamp) or similar covering both
        has_composite = any(
            "user_id" in sql and "timestamp" in sql
            for sql in index_sqls.values()
        )
        assert has_composite, (
            f"Expected composite index on (user_id, timestamp). "
            f"Found indexes: {index_sqls}"
        )


class TestSessionsSchema:
    """Schema validation for sessions table."""

    @pytest.mark.asyncio
    async def test_sessions_table_exists(self, db: Storage) -> None:
        """sessions table is created by initialize()."""
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        row = await cursor.fetchone()
        assert row is not None, "sessions table should exist after initialize()"

    @pytest.mark.asyncio
    async def test_sessions_table_has_user_id_pk(self, db: Storage) -> None:
        """sessions table has user_id as PRIMARY KEY."""
        cursor = await db._db.execute("PRAGMA table_info(sessions)")
        rows = await cursor.fetchall()
        columns = {r["name"]: r for r in rows}

        assert "user_id" in columns, "sessions table must have user_id column"
        assert columns["user_id"]["pk"] == 1, "user_id must be the primary key"


class TestSessionIdPersistence:
    """Tests for get_session_id / save_session_id."""

    @pytest.mark.asyncio
    async def test_save_and_load_session_id(self, db: Storage) -> None:
        """session_id is persisted and retrievable."""
        await db.save_session_id("alice", "session-abc-123")
        loaded = await db.get_session_id("alice")
        assert loaded == "session-abc-123"

    @pytest.mark.asyncio
    async def test_get_session_id_missing_returns_none(self, db: Storage) -> None:
        """get_session_id returns None for unknown user."""
        result = await db.get_session_id("ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_session_id_is_idempotent(self, db: Storage) -> None:
        """save_session_id replaces existing value (upsert semantics)."""
        await db.save_session_id("alice", "id-v1")
        await db.save_session_id("alice", "id-v2")
        loaded = await db.get_session_id("alice")
        assert loaded == "id-v2"
