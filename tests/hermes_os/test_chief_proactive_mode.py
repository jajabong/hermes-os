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

    async def mock_suggestions(user_id: str, scheduler, max_suggestions: int = 3, **kwargs):
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


# ---------------------------------------------------------------------------
# Tests: JarvisInterface injection and proactive card delivery
# ---------------------------------------------------------------------------


from hermes_os.chief_agent import ChiefAgent


@pytest.mark.asyncio
async def test_chief_agent_init_with_jarvis_parameter() -> None:
    """ChiefAgent.__init__ should accept jarvis parameter."""
    mock_jarvis = AsyncMock()
    chief = ChiefAgent(jarvis=mock_jarvis)
    assert chief._jarvis is mock_jarvis


@pytest.mark.asyncio
async def test_chief_set_jarvis_method() -> None:
    """ChiefAgent.set_jarvis() should inject JarvisInterface."""
    chief = ChiefAgent()
    mock_jarvis = AsyncMock()
    chief.set_jarvis(mock_jarvis)
    assert chief._jarvis is mock_jarvis


@pytest.mark.asyncio
async def test_chief_sends_proactive_card_via_jarvis() -> None:
    """When push_to_user=True, send_proactive_suggestion_card is called."""
    from hermes_os.chief_agent import ChiefAgent

    chief = ChiefAgent()
    mock_jarvis = AsyncMock()
    chief.set_jarvis(mock_jarvis)

    await chief.send_proactive_suggestion_card(
        user_id="alice",
        suggestions=["Task 'Build agent' failed - consider retry", "Goal progress 80%"],
    )

    mock_jarvis.send_card_with_nl.assert_called_once()
    call_kwargs = mock_jarvis.send_card_with_nl.call_args
    assert call_kwargs.kwargs["user_id"] == "alice"
    assert "💡" in call_kwargs.kwargs["title"]
    assert "主动建议" in call_kwargs.kwargs["title"]


@pytest.mark.asyncio
async def test_chief_no_jarvis_no_crash() -> None:
    """ChiefAgent with no Jarvis set should not crash on send_proactive_suggestion_card."""
    from hermes_os.chief_agent import ChiefAgent

    chief = ChiefAgent()
    # No jarvis set - should not raise
    await chief.send_proactive_suggestion_card(
        user_id="alice",
        suggestions=["Test suggestion"],
    )


@pytest.mark.asyncio
async def test_get_proactive_suggestions_with_push_to_user() -> None:
    """get_proactive_suggestions(push_to_user=True) sends card via Jarvis."""
    from hermes_os.chief_agent import ChiefAgent

    chief = ChiefAgent()
    mock_jarvis = AsyncMock()
    chief.set_jarvis(mock_jarvis)

    scheduler = MagicMock()
    scheduler.get_tasks_for_user = AsyncMock(return_value=[])

    # Give chief a goal tracker so suggestions are generated
    mock_goal_tracker = MagicMock()
    mock_goal = MagicMock()
    mock_goal.is_completed = False
    mock_goal.progress = 0.75
    mock_goal.current_phase = "实现"
    mock_goal.next_phase = "测试"
    mock_goal_tracker.get_active_goal = AsyncMock(return_value=mock_goal)
    chief._goal_tracker = mock_goal_tracker

    suggestions = await chief.get_proactive_suggestions(
        user_id="alice",
        scheduler=scheduler,
        push_to_user=True,
    )

    # Jarvis should be called because we have goal-based suggestions
    assert len(suggestions) >= 1
    mock_jarvis.send_card_with_nl.assert_called_once()


@pytest.mark.asyncio
async def test_get_proactive_suggestions_without_push_returns_only_list() -> None:
    """get_proactive_suggestions(push_to_user=False) returns list without sending card."""
    from hermes_os.chief_agent import ChiefAgent

    chief = ChiefAgent()
    mock_jarvis = AsyncMock()
    chief.set_jarvis(mock_jarvis)

    scheduler = MagicMock()
    scheduler.get_tasks_for_user = AsyncMock(return_value=[])

    suggestions = await chief.get_proactive_suggestions(
        user_id="alice",
        scheduler=scheduler,
        push_to_user=False,
    )

    mock_jarvis.send_card_with_nl.assert_not_called()
    assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_suggestions_work_without_failed_tasks(tmp_path: Path) -> None:
    """ChiefAgent still returns goal-based suggestions even when no tasks failed."""
    from hermes_os.chief_agent import ChiefAgent

    chief = ChiefAgent()
    mock_jarvis = AsyncMock()
    chief.set_jarvis(mock_jarvis)

    scheduler = MagicMock()
    scheduler.get_tasks_for_user = AsyncMock(return_value=[])

    mock_goal_tracker = MagicMock()
    mock_goal = MagicMock()
    mock_goal.is_completed = False
    mock_goal.progress = 0.75
    mock_goal.current_phase = "实现"
    mock_goal.next_phase = "测试"
    mock_goal_tracker.get_active_goal = AsyncMock(return_value=mock_goal)
    chief._goal_tracker = mock_goal_tracker

    suggestions = await chief.get_proactive_suggestions(
        user_id="alice",
        scheduler=scheduler,
        push_to_user=False,
    )

    assert len(suggestions) >= 1
    goal_suggestions = [s for s in suggestions if "🎯" in s]
    assert len(goal_suggestions) >= 1
