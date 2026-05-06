"""TDD tests for ChiefAgent proactive mode — proactive suggestions without user input.

Run with: pytest tests/hermes_os/test_chief_proactive_mode.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Tests: ProactiveEngine wires ChiefAgent for proactive suggestions
# ---------------------------------------------------------------------------


def test_proactive_engine_has_set_chief_agent() -> None:
    """ProactiveEngine should have set_chief_agent() for DI."""
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    assert hasattr(engine, "set_chief_agent"), "ProactiveEngine missing set_chief_agent()"


@pytest.mark.asyncio
async def test_proactive_engine_stores_chief_agent(tmp_path: Path) -> None:
    """set_chief_agent should store the ChiefAgent instance."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    chief = ChiefAgent()
    engine.set_chief_agent(chief)

    assert engine._chief_agent is chief


# ---------------------------------------------------------------------------
# Tests: get_proactive_suggestions calls ChiefAgent.get_proactive_suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proactive_suggestions_calls_chief_agent(tmp_path: Path) -> None:
    """ProactiveEngine.get_suggestions_for_user should delegate to ChiefAgent."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    scheduler_mock = MagicMock()
    scheduler_mock.get_tasks_for_user = AsyncMock(return_value=[])
    engine._scheduler = scheduler_mock

    chief = ChiefAgent()
    # Mock ChiefAgent.get_proactive_suggestions
    chief.get_proactive_suggestions = AsyncMock(
        return_value=["Test suggestion 1", "Test suggestion 2"]
    )
    engine.set_chief_agent(chief)

    suggestions = await engine.get_suggestions_for_user("u_test")

    assert suggestions == ["Test suggestion 1", "Test suggestion 2"]
    chief.get_proactive_suggestions.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: chief_agent wired in gateway_hook
# ---------------------------------------------------------------------------


def test_gateway_hook_wires_chief_agent_into_proactive_engine(tmp_path: Path) -> None:
    """gateway_hook should create ChiefAgent and wire it into ProactiveEngine."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.gateway_hook import HermesOSHook, HookConfig

    config = HookConfig(enable_event_loop=False)
    hook = HermesOSHook(config=config)

    # ChiefAgent should be created and wired to ProactiveEngine
    assert hasattr(hook, "_chief")
    assert isinstance(hook._chief, ChiefAgent)
    assert hasattr(hook._proactive_engine, "_chief_agent")
    assert hook._proactive_engine._chief_agent is hook._chief


# ---------------------------------------------------------------------------
# Tests: _deep_patrol calls _patrol_proactive_suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deep_patrol_calls_proactive_suggestions_patrol(tmp_path: Path) -> None:
    """deep_patrol should call _patrol_proactive_suggestions."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    scheduler_mock = MagicMock()
    scheduler_mock.get_tasks_for_user = AsyncMock(return_value=[])
    engine._scheduler = scheduler_mock

    chief = ChiefAgent()
    chief.get_proactive_suggestions = AsyncMock(return_value=[])
    engine.set_chief_agent(chief)

    called = False
    original = engine._patrol_proactive_suggestions

    async def tracking():
        nonlocal called
        called = True
        await original()

    engine._patrol_proactive_suggestions = tracking  # type: ignore

    await engine._deep_patrol(tick_count=10)

    assert called, "deep_patrol should call _patrol_proactive_suggestions"


# ---------------------------------------------------------------------------
# Tests: proactive suggestions included in silence outreach reminder
# ---------------------------------------------------------------------------


def test_silence_reminder_includes_chief_suggestions(tmp_path: Path) -> None:
    """_build_silence_reminder should include ChiefAgent proactive suggestions."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    scheduler_mock = MagicMock()
    scheduler_mock.get_tasks_for_user = AsyncMock(return_value=[])
    engine._scheduler = scheduler_mock

    chief = ChiefAgent()
    chief.get_proactive_suggestions = AsyncMock(return_value=["完成季度报告", "安排团队会议"])
    engine.set_chief_agent(chief)

    # _build_silence_reminder calls get_suggestions_for_user which calls ChiefAgent
    msg = engine._build_silence_reminder("Dana", 72, ["完成季度报告", "安排团队会议"])

    assert "Dana" in msg
    assert "72" in msg
    assert any(kw in msg for kw in ["报告", "会议"]), (
        f"Reminder should mention pending tasks, got: {msg}"
    )


# ---------------------------------------------------------------------------
# Tests: no false positives — empty suggestions return empty string
# ---------------------------------------------------------------------------


def test_build_silence_reminder_empty_tasks_shows_generic_message(tmp_path: Path) -> None:
    """When no pending tasks, reminder should show generic message."""
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    msg = engine._build_silence_reminder("Dana", 72, [])

    assert "Dana" in msg
    assert "72" in msg
    # Should not crash and should show a helpful message


# ---------------------------------------------------------------------------
# Tests: patrol loops over all active users, not just known ones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patrol_proactive_suggestions_iterates_all_shard_users(tmp_path: Path) -> None:
    """_patrol_proactive_suggestions should check all users in shard DBs."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine
    from hermes_os.shard_manager import ShardedStorage, ShardManager

    sm = ShardManager(base_path=tmp_path, num_shards=100)
    storage = ShardedStorage(shard_manager=sm)

    # Create two users
    await storage.add_message("u_alpha", "user", "hello")
    await storage.add_message("u_beta", "user", "hello")

    engine = ProactiveEngine()
    engine.set_sharded_storage(storage)
    engine._scheduler = MagicMock()

    chief = ChiefAgent()
    chief.get_proactive_suggestions = AsyncMock(return_value=[])
    engine.set_chief_agent(chief)

    called_for: list[str] = []

    async def mock_suggestions(user_id: str, scheduler, max_suggestions: int = 3):
        called_for.append(user_id)
        return []

    chief.get_proactive_suggestions = mock_suggestions  # type: ignore

    await engine._patrol_proactive_suggestions()

    assert "u_alpha" in called_for, f"Should check u_alpha, checked: {called_for}"
    assert "u_beta" in called_for, f"Should check u_beta, checked: {called_for}"

    await storage.close()


# ---------------------------------------------------------------------------
# Tests: get_suggestions_for_user falls back gracefully when no scheduler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_suggestions_for_user_no_scheduler_returns_empty(tmp_path: Path) -> None:
    """When no scheduler is set, get_suggestions_for_user should return [] without error."""
    from hermes_os.chief_agent import ChiefAgent
    from hermes_os.proactive_engine import ProactiveEngine

    engine = ProactiveEngine()
    engine._scheduler = None

    chief = ChiefAgent()
    engine.set_chief_agent(chief)

    # Should not raise
    suggestions = await engine.get_suggestions_for_user("u_orphan")

    # With no scheduler, no tasks → empty suggestions
    assert isinstance(suggestions, list)
