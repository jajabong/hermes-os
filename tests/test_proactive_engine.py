"""Tests for ProactiveEngine scheduled workflow execution."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from hermes_os.event_loop import Event, EventType
from hermes_os.proactive_engine import ProactiveEngine
from hermes_os.task_scheduler import Task, TaskStatus, TaskPriority


class TestProactiveEngineScheduledWorkflow:
    """Tests for CRON-triggered daily briefing workflow."""

    def test_register_with_loop_registers_cron_tick(self) -> None:
        """register_with_loop() registers the CRON_TICK handler."""
        engine = ProactiveEngine()
        mock_loop = MagicMock()
        mock_loop.register_handler = MagicMock()

        engine.register_with_loop(mock_loop)

        calls = mock_loop.register_handler.call_args_list
        registered_types = [c[0][0] for c in calls]
        assert EventType.CRON_TICK in registered_types
        assert EventType.TASK_COMPLETED in registered_types
        assert EventType.TASK_FAILED in registered_types

    @pytest.mark.asyncio
    async def test_on_cron_tick_calls_deep_patrol_periodically(self) -> None:
        """on_cron_tick triggers deep patrol every N ticks."""
        engine = ProactiveEngine()
        engine._deep_patrol = AsyncMock()
        engine._shallow_patrol = AsyncMock()

        # Tick 1 — shallow only
        event = Event(type=EventType.CRON_TICK, payload={"tick_count": 1})
        await engine.on_cron_tick(event)
        engine._shallow_patrol.assert_called_once_with(1)
        engine._deep_patrol.assert_not_called()

        # Reset mock
        engine._deep_patrol.reset_mock()
        engine._shallow_patrol.reset_mock()

        # Tick 6 (>= 5 interval) — both
        event = Event(type=EventType.CRON_TICK, payload={"tick_count": 6})
        await engine.on_cron_tick(event)
        engine._deep_patrol.assert_called_once_with(6)
        engine._shallow_patrol.assert_called_once_with(6)

    @pytest.mark.asyncio
    async def test_shallow_patrol_logs_task_stats(self) -> None:
        """_shallow_patrol logs task statistics without blocking."""
        engine = ProactiveEngine()
        mock_scheduler = MagicMock()
        mock_scheduler.get_all_tasks = AsyncMock(return_value=[
            Task(task_id="t1", user_id="alice", title="Task 1", description="",
                 status=TaskStatus.FAILED, priority=TaskPriority.NORMAL),
            Task(task_id="t2", user_id="alice", title="Task 2", description="",
                 status=TaskStatus.BLOCKED, priority=TaskPriority.NORMAL),
        ])
        engine._scheduler = mock_scheduler

        await engine._shallow_patrol(tick_count=10)

        # Should not raise — just logs


class TestProactiveEngineWorkflowExecution:
    """Tests for ProactiveEngine executing workflows on schedule."""

    @pytest.mark.asyncio
    async def test_execute_scheduled_workflow_for_user(self) -> None:
        """execute_scheduled_workflow() runs a workflow for a specific user."""
        engine = ProactiveEngine()
        mock_workflow = MagicMock()
        mock_workflow.execute = AsyncMock(return_value=MagicMock(
            success=True,
            results=["meeting1", "meeting2"],
            error=None,
        ))

        engine._workflow_engine = mock_workflow
        result = await engine.execute_scheduled_workflow(
            user_id="alice",
            workflow_name="daily_briefing",
        )

        mock_workflow.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_scheduled_workflow_sends_feishu_card(self) -> None:
        """Completed scheduled workflow sends result to user via Feishu."""
        engine = ProactiveEngine()
        mock_workflow = MagicMock()
        mock_result = MagicMock(
            success=True,
            results=["Calendar: 2 events", "Tasks: 5 pending"],
        )
        mock_result.to_feishu_card = MagicMock(return_value={"header": {"title": {"content": "Daily"}}, "elements": [{"text": {"content": "content"}}]})
        mock_workflow.execute = AsyncMock(return_value=mock_result)
        mock_jarvis = MagicMock()
        mock_jarvis.send_card_with_nl = AsyncMock()
        engine._workflow_engine = mock_workflow
        engine._jarvis = mock_jarvis

        await engine.execute_scheduled_workflow(
            user_id="alice",
            workflow_name="daily_briefing",
        )

        mock_jarvis.send_card_with_nl.assert_called()


class TestProactiveEngineUserOptIn:
    """Tests for per-user scheduled briefing opt-in."""

    @pytest.mark.asyncio
    async def test_get_users_with_daily_briefing_enabled(self) -> None:
        """_get_users_with_daily_briefing_enabled() returns users who opted in."""
        engine = ProactiveEngine()
        mock_registry = MagicMock()
        mock_registry.list_users_with_flag = AsyncMock(return_value=[
            "alice", "bob"
        ])
        engine._user_registry = mock_registry

        users = await engine._get_users_with_daily_briefing_enabled()
        assert "alice" in users
        assert "bob" in users
