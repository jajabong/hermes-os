"""TDD tests for silence detection + proactive outreach.

These tests define the expected behavior BEFORE implementation.
Run with: pytest tests/hermes_os/test_silence_detection.py -v
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Tests: conversation_states.last_message_at tracking
# ---------------------------------------------------------------------------

def test_conversation_states_has_last_message_at_column(tmp_path: Path) -> None:
    """The conversation_states table should have a last_message_at column for silence tracking."""
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def check():
        conn = await storage._get_db_for("u_silence")
        await storage._lazy_initialize(conn, "u_silence")
        async with conn.execute("PRAGMA table_info(conversation_states)") as cur:
            rows = await cur.fetchall()
        cols = {row[1] for row in rows}
        return cols

    cols = asyncio.run(check())
    assert "last_message_at" in cols, f"missing last_message_at column, found: {cols}"


def test_add_message_updates_last_message_at(tmp_path: Path) -> None:
    """Adding a message should update last_message_at in conversation_states."""
    import sqlite3
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def run():
        # First message
        conn = await storage._get_db_for("u_silence")
        await storage.add_message("u_silence", "user", "hello")

        # Check last_message_at was set
        row = await storage.get_conversation_state("u_silence")
        assert row is not None
        last_msg_at = row["last_message_at"]
        assert last_msg_at is not None

        # Check it's recent (within last minute)
        last_msg = datetime.fromisoformat(last_msg_at)
        assert (datetime.now(UTC) - last_msg) < timedelta(minutes=1)

    asyncio.run(run())


def test_get_conversation_state_returns_last_message_at(tmp_path: Path) -> None:
    """get_conversation_state() should return last_message_at timestamp."""
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def run():
        await storage.add_message("u_silence", "user", "hello")
        state = await storage.get_conversation_state("u_silence")
        assert state is not None
        assert state["last_message_at"] is not None

    asyncio.run(run())


def test_last_message_at_persists_after_reconnect(tmp_path: Path) -> None:
    """last_message_at should persist across connection resets."""
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage1 = ShardedStorage(shard_manager=sm)
    storage2 = ShardedStorage(shard_manager=sm)

    async def run():
        # Add message via first storage
        await storage1.add_message("u_silence", "user", "hello")
        ts1 = await storage1.get_conversation_state("u_silence")

        # Close and reopen via second storage (simulates process restart)
        await storage1.close()
        await storage2._get_db_for("u_silence")  # Force reconnect

        ts2 = await storage2.get_conversation_state("u_silence")
        assert ts2 is not None
        assert ts2["last_message_at"] == ts1["last_message_at"]

        await storage2.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Tests: silence detection thresholds
# ---------------------------------------------------------------------------

def test_silence_threshold_constants_defined() -> None:
    """Silence threshold constants should be defined in proactive_engine."""
    from hermes_os.proactive_engine import (
        SILENCE_GREETING_HOURS,
        SILENCE_REMINDER_HOURS,
        SILENCE_URGENT_HOURS,
    )

    assert SILENCE_GREETING_HOURS == 24, "Greeting threshold should be 24h"
    assert SILENCE_REMINDER_HOURS == 72, "Reminder threshold should be 72h"
    assert SILENCE_URGENT_HOURS == 168, "Urgent threshold should be 168h (1 week)"


def test_silence_levels_are_distinct() -> None:
    """Silence levels must be strictly increasing."""
    from hermes_os.proactive_engine import (
        SILENCE_GREETING_HOURS,
        SILENCE_REMINDER_HOURS,
        SILENCE_URGENT_HOURS,
    )

    assert SILENCE_GREETING_HOURS < SILENCE_REMINDER_HOURS
    assert SILENCE_REMINDER_HOURS < SILENCE_URGENT_HOURS


# ---------------------------------------------------------------------------
# Tests: ProactiveEngine silence detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_silent_users_returns_list(tmp_path: Path) -> None:
    """_detect_silent_users() should return a list of silent user dicts."""
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def setup_users():
        # User "active" - messaged 1 hour ago
        await storage.add_message("u_active", "user", "hello")
        # User "silent_25h" - messaged 25 hours ago
        await storage.add_message("u_silent_25h", "user", "hello")
        # User "silent_100h" - messaged 100 hours ago
        await storage.add_message("u_silent_100h", "user", "hello")

    await setup_users()

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)

    # Backdate last_message_at for silent users
    conn = await storage._get_db_for("u_silent_25h")
    old_ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    await conn.execute(
        "UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?",
        (old_ts, "u_silent_25h"),
    )
    await conn.commit()

    conn2 = await storage._get_db_for("u_silent_100h")
    very_old_ts = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    await conn2.execute(
        "UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?",
        (very_old_ts, "u_silent_100h"),
    )
    await conn2.commit()

    silent_users = await engine._detect_silent_users()

    assert len(silent_users) >= 2, f"Expected at least 2 silent users, got {len(silent_users)}"
    user_ids = [u["user_id"] for u in silent_users]
    assert "u_silent_25h" in user_ids
    assert "u_silent_100h" in user_ids
    assert "u_active" not in user_ids

    await storage.close()


@pytest.mark.asyncio
async def test_detect_silent_users_classifies_by_threshold(tmp_path: Path) -> None:
    """Silent users should be classified by silence level (greeting/reminder/urgent)."""
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def setup():
        # 25h silent -> greeting level
        await storage.add_message("u_25h", "user", "hello")
        conn = await storage._get_db_for("u_25h")
        old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        await conn.execute("UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?", (old, "u_25h"))
        await conn.commit()

        # 100h silent -> reminder level
        await storage.add_message("u_100h", "user", "hello")
        conn2 = await storage._get_db_for("u_100h")
        old2 = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
        await conn2.execute("UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?", (old2, "u_100h"))
        await conn2.commit()

    await setup()

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)

    silent = await engine._detect_silent_users()
    user_map = {u["user_id"]: u for u in silent}

    assert "u_25h" in user_map
    assert user_map["u_25h"]["silence_level"] == "greeting"

    assert "u_100h" in user_map
    assert user_map["u_100h"]["silence_level"] == "reminder"

    await storage.close()


@pytest.mark.asyncio
async def test_on_user_silent_hook_is_called(tmp_path: Path) -> None:
    """on_user_silent(user_id, hours, level) should be called for each silent user."""
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    async def setup():
        await storage.add_message("u_silent", "user", "hello")
        conn = await storage._get_db_for("u_silent")
        old = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
        await conn.execute("UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?", (old, "u_silent"))
        await conn.commit()

    await setup()

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)

    called = []
    original_handler = engine.on_user_silent

    async def tracking_handler(user_id, hours, level):
        called.append((user_id, hours, level))
        await original_handler(user_id, hours, level)

    engine.on_user_silent = tracking_handler  # type: ignore

    await engine._detect_and_reach_out()

    assert len(called) >= 1
    assert called[0][0] == "u_silent"
    assert called[0][2] == "greeting"

    await storage.close()


# ---------------------------------------------------------------------------
# Tests: proactive outreach messages
# ---------------------------------------------------------------------------

def test_silence_greeting_message_format() -> None:
    """_build_silence_greeting() should return a friendly greeting card."""
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    msg = engine._build_silence_greeting("Dana", 25)

    assert "Dana" in msg
    assert "25" in msg
    assert len(msg) < 500, "Greeting should be concise (<500 chars)"


def test_silence_reminder_message_format() -> None:
    """_build_silence_reminder() should include goal/task context."""
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    msg = engine._build_silence_reminder("Dana", 72, ["完成季度报告", "安排会议"])

    assert "Dana" in msg
    assert "72" in msg
    # Should reference pending items
    assert any(kw in msg for kw in ["报告", "会议", "任务"])


# ---------------------------------------------------------------------------
# Tests: ShardedStorage.add_message updates last_message_at
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_message_updates_last_message_at_on_every_call(tmp_path: Path) -> None:
    """Every add_message call should update last_message_at, not just the first."""
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    await storage.add_message("u_test", "user", "first")
    ts1 = await storage.get_conversation_state("u_test")

    await asyncio.sleep(0.01)

    await storage.add_message("u_test", "assistant", "reply")
    ts2 = await storage.get_conversation_state("u_test")

    assert ts1 is not None
    assert ts2 is not None
    t1 = datetime.fromisoformat(ts1["last_message_at"])
    t2 = datetime.fromisoformat(ts2["last_message_at"])
    assert t2 >= t1, "last_message_at should advance on each message"

    await storage.close()


# ---------------------------------------------------------------------------
# Tests: silence detection wiring into deep_patrol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deep_patrol_calls_silence_detection(tmp_path: Path) -> None:
    """deep_patrol should call _detect_and_reach_out as part of patrol cycle."""
    from hermes_os.proactive_engine import ProactiveEngine, _DEEP_PATROL_INTERVAL
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    await storage.add_message("u_active", "user", "hello")
    await storage.add_message("u_silent", "user", "hello")
    conn = await storage._get_db_for("u_silent")
    old = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
    await conn.execute("UPDATE conversation_states SET last_message_at = ? WHERE user_id = ?", (old, "u_silent"))
    await conn.commit()

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)
    # Provide a minimal mock scheduler so _deep_patrol doesn't return early
    engine._scheduler = MagicMock()

    called = False
    original = engine._detect_and_reach_out

    async def tracking():
        nonlocal called
        called = True
        await original()

    engine._detect_and_reach_out = tracking  # type: ignore

    # Use tick_count=10 so the deep patrol condition (tick - last >= 5) is True
    await engine._deep_patrol(tick_count=10)

    assert called, "deep_patrol should call _detect_and_reach_out"

    await storage.close()


# ---------------------------------------------------------------------------
# Tests: no false positives on active users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recently_active_user_not_flagged_silent(tmp_path: Path) -> None:
    """Users who messaged within SILENCE_GREETING_HOURS should not be flagged."""
    from hermes_os.proactive_engine import ProactiveEngine, SILENCE_GREETING_HOURS
    from hermes_os.shard_manager import ShardManager, ShardedStorage

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    await storage.add_message("u_recent", "user", "hello")

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)

    silent = await engine._detect_silent_users()
    user_ids = [u["user_id"] for u in silent]

    assert "u_recent" not in user_ids, "Recently active user should not be flagged as silent"

    await storage.close()
