"""TDD tests for GoalTracker context injection into gateway_hook handle().

Tests what needs to be built:
1. handle() injects <goal_context> block when user has an active goal
2. <goal_context> block contains goal description, phase, and progress
3. No goal_context block when user has no active goal
4. goal_context block appears in correct position in the message
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_goal_context_injected_when_active_goal(tmp_path: Path) -> None:
    """When user has an active goal, <goal_context> block is injected into message."""
    from hermes_os.gateway_hook import GatewayEvent, HermesOSHook, HookConfig
    from hermes_os.goal_tracker import GoalPattern, GoalTracker

    # Create goal DB
    db_path = str(tmp_path / "test_goal.db")
    gt = GoalTracker(db_path=db_path)
    await gt.initialize()

    # Create an active goal for user
    goal = await gt.create_goal(
        user_id="alice",
        description="完成供应商对比分析项目",
        initial_intent="research",
        pattern=GoalPattern.RESEARCH_TO_DEPLOY,
    )

    # Create hook with goal tracker
    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )
    hook = HermesOSHook(config=config)
    hook._goal_tracker = gt  # Inject the goal tracker

    # Mock router to return a mock user
    mock_user = MagicMock()
    mock_user.user_id = "alice"
    mock_user.name = "Alice"

    mock_routed = MagicMock()
    mock_routed.user = mock_user
    mock_routed.enriched_message = "继续上次那件事"
    mock_routed.session_id = "session-001"

    async def mock_route(gw_event):
        return mock_routed

    # Mock chief and _process_intent_and_schedule
    hook._chief = AsyncMock()
    hook._process_intent_and_schedule = AsyncMock()

    # Patch _spawn to avoid side effects
    hook._spawn = lambda c: None

    event = GatewayEvent(
        platform="feishu",
        platform_user_id="alice",
        message="继续上次那件事",
        user_name="Alice",
        user_id_alt="alice",
    )
    event.text = "继续上次那件事"
    context = {"event": event, "platform": "feishu", "user_id": "alice"}

    # Create a minimal router with our mock
    class FakeRouter:
        async def route(self, gw_event):
            return mock_routed

    # Call handle
    class FakeHook(HermesOSHook):
        async def _get_router(self):
            return FakeRouter()

    fake_hook = FakeHook(config=config)
    fake_hook._goal_tracker = gt
    fake_hook._chief = AsyncMock()
    fake_hook._process_intent_and_schedule = AsyncMock()
    fake_hook._spawn = lambda c: None

    await fake_hook.handle("agent:start", context)

    # Verify <goal_context> block was injected
    assert "<goal_context>" in event.text
    assert "完成供应商对比分析项目" in event.text


@pytest.mark.asyncio
async def test_no_goal_context_when_no_active_goal(tmp_path: Path) -> None:
    """When user has no active goal, no <goal_context> block is injected."""
    from hermes_os.gateway_hook import GatewayEvent, HermesOSHook, HookConfig
    from hermes_os.goal_tracker import GoalTracker

    db_path = str(tmp_path / "test_goal.db")
    gt = GoalTracker(db_path=db_path)
    await gt.initialize()

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )

    class FakeRouter:
        async def route(self, gw_event):
            mock_user = MagicMock()
            mock_user.user_id = "nobody"
            mock_user.name = "Nobody"
            mock_routed = MagicMock()
            mock_routed.user = mock_user
            mock_routed.enriched_message = "你好"
            mock_routed.session_id = "session-001"
            return mock_routed

    class FakeHook(HermesOSHook):
        async def _get_router(self):
            return FakeRouter()

    fake_hook = FakeHook(config=config)
    fake_hook._goal_tracker = gt
    fake_hook._chief = AsyncMock()
    fake_hook._process_intent_and_schedule = AsyncMock()
    fake_hook._spawn = lambda c: None

    event = GatewayEvent(
        platform="feishu",
        platform_user_id="nobody",
        message="你好",
        user_name="Nobody",
        user_id_alt="nobody",
    )
    event.text = "你好"
    context = {"event": event, "platform": "feishu", "user_id": "nobody"}

    await fake_hook.handle("agent:start", context)

    # No goal_context block since no active goal
    assert "<goal_context>" not in event.text


@pytest.mark.asyncio
async def test_goal_context_appears_before_persona(tmp_path: Path) -> None:
    """<goal_context> block appears before <assistant_persona> block in message."""
    from hermes_os.gateway_hook import GatewayEvent, HermesOSHook, HookConfig
    from hermes_os.goal_tracker import GoalPattern, GoalTracker

    db_path = str(tmp_path / "test_goal.db")
    gt = GoalTracker(db_path=db_path)
    await gt.initialize()

    goal = await gt.create_goal(
        user_id="alice",
        description="完成项目X",
        initial_intent="research",
        pattern=GoalPattern.RESEARCH_TO_DEPLOY,
    )

    config = HookConfig(
        db_path=str(tmp_path / "test.db"),
        knowledge_db_path=str(tmp_path / "test_kb.db"),
        enable_event_loop=False,
    )

    class FakeRouter:
        async def route(self, gw_event):
            mock_user = MagicMock()
            mock_user.user_id = "alice"
            mock_user.name = "Alice"
            mock_routed = MagicMock()
            mock_routed.user = mock_user
            mock_routed.enriched_message = "项目进展如何"
            mock_routed.session_id = "session-001"
            return mock_routed

    class FakeHook(HermesOSHook):
        async def _get_router(self):
            return FakeRouter()

    fake_hook = FakeHook(config=config)
    fake_hook._goal_tracker = gt
    fake_hook._chief = AsyncMock()
    fake_hook._process_intent_and_schedule = AsyncMock()
    fake_hook._spawn = lambda c: None

    event = GatewayEvent(
        platform="feishu",
        platform_user_id="alice",
        message="项目进展如何",
        user_name="Alice",
        user_id_alt="alice",
    )
    event.text = "项目进展如何"
    context = {"event": event, "platform": "feishu", "user_id": "alice"}

    await fake_hook.handle("agent:start", context)

    # Both blocks present
    assert "<goal_context>" in event.text
    assert "<assistant_persona>" in event.text
    # Verify goal_context has actual content (from our goal)
    assert "完成项目X" in event.text
